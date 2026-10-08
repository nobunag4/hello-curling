"""Banco SQLite do Hello, Curling.

Princípio: separar o que cada fonte diz (chaves da fonte) das entidades nossas (pessoa, time, evento).
A tabela `link` guarda como cada chave de fonte foi ligada a uma entidade nossa, com método e confiança,
para que toda ligação possa ser auditada e desfeita.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "hello_curling.sqlite"

SCHEMA = """
PRAGMA foreign_keys = ON;

-- Pessoas (atletas, técnicos). wcf_id é a âncora oficial quando existe.
CREATE TABLE IF NOT EXISTS person (
  id          INTEGER PRIMARY KEY,
  wcf_id      INTEGER UNIQUE,
  name        TEXT NOT NULL,          -- nome de exibição
  gender      TEXT,                   -- 'M' | 'F'
  born        TEXT,                   -- AAAA-MM-DD
  delivery    TEXT,                   -- 'right' | 'left'
  nations     TEXT,                   -- JSON: seleções que já defendeu, segundo a World Curling
  merged_into INTEGER REFERENCES person(id),
  profile_at  TEXT                    -- quando a página pessoal foi lida
);

-- Todas as grafias vistas de cada pessoa, para busca e para ligar fontes sem código
CREATE TABLE IF NOT EXISTS person_name (
  person_id INTEGER NOT NULL REFERENCES person(id),
  raw       TEXT NOT NULL,
  key       TEXT NOT NULL,            -- names.key(raw)
  source    TEXT NOT NULL,
  seen      INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (person_id, key)
);
CREATE INDEX IF NOT EXISTS person_name_key ON person_name(key);

-- Como cada chave de fonte foi ligada a uma entidade nossa
CREATE TABLE IF NOT EXISTS link (
  source     TEXT NOT NULL,           -- 'wcf', 'gsoc', 'wcf-live', ...
  kind       TEXT NOT NULL,           -- 'person', 'squad', ...
  key        TEXT NOT NULL,           -- chave na fonte (id, ou nome normalizado + contexto)
  entity_id  INTEGER NOT NULL,
  method     TEXT NOT NULL,           -- 'anchor' | 'auto' | 'override' | 'review'
  confidence REAL NOT NULL,
  note       TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (source, kind, key)
);

-- Fila de casos duvidosos para revisão humana
CREATE TABLE IF NOT EXISTS review (
  id         INTEGER PRIMARY KEY,
  kind       TEXT NOT NULL,           -- 'person_link' | 'person_duplicate'
  subject    TEXT NOT NULL,           -- o que se tentou ligar (JSON)
  candidates TEXT NOT NULL,           -- JSON [{id, name, score, why}]
  status     TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (kind, subject)
);

CREATE TABLE IF NOT EXISTS event (
  id         TEXT PRIMARY KEY,        -- 'wcf:809'
  source     TEXT NOT NULL,
  type_id    INTEGER,
  type_name  TEXT,
  discipline TEXT,                    -- 'teams' | 'mixed_doubles' | 'mixed' | 'wheelchair' ...
  division   TEXT,                    -- 'Men' | 'Women' | 'Mixed Doubles' ...
  name       TEXT NOT NULL,
  year       INTEGER,
  season     TEXT,                    -- '2025-26'
  venue      TEXT,
  city       TEXT,
  country    TEXT,
  start_date TEXT,
  end_date   TEXT,
  complete   INTEGER NOT NULL DEFAULT 0,
  fetched_at TEXT
);

-- Um time num evento (seleção, ou time do circuito)
CREATE TABLE IF NOT EXISTS entry (
  id       INTEGER PRIMARY KEY,
  event_id TEXT NOT NULL REFERENCES event(id),
  name     TEXT NOT NULL,             -- como a fonte chama o time ('Italy', 'Team Hasselborg')
  club     TEXT,                      -- clube que representou o país (campeonatos antigos)
  nation   TEXT,
  rank     INTEGER,
  wins     INTEGER,
  losses   INTEGER,
  grp      TEXT,
  squad_id INTEGER REFERENCES squad(id),
  UNIQUE (event_id, name)
);

CREATE TABLE IF NOT EXISTS entry_member (
  entry_id  INTEGER NOT NULL REFERENCES entry(id),
  person_id INTEGER NOT NULL REFERENCES person(id),
  role      TEXT NOT NULL,            -- fourth|third|second|lead|alternate|player|coach|official
  is_skip   INTEGER NOT NULL DEFAULT 0,
  ord       INTEGER NOT NULL,
  label     TEXT,
  PRIMARY KEY (entry_id, person_id, role)
);

CREATE TABLE IF NOT EXISTS game (
  id          TEXT PRIMARY KEY,       -- 'wcf:809:12'
  event_id    TEXT NOT NULL REFERENCES event(id),
  ord         INTEGER NOT NULL,
  draw        TEXT,
  stage       TEXT,                   -- round_robin | tiebreaker | playoff | bronze | final
  start_local TEXT,                   -- horário local da sede, sem fuso
  sheet       TEXT,
  entry1      INTEGER REFERENCES entry(id),
  entry2      INTEGER REFERENCES entry(id),
  score1      INTEGER,
  score2      INTEGER,
  hammer      INTEGER,                -- quem tinha o hammer no 1º end: 1 | 2
  ends1       TEXT,                   -- JSON
  ends2       TEXT
);
CREATE INDEX IF NOT EXISTS game_event ON game(event_id);
CREATE INDEX IF NOT EXISTS game_e1 ON game(entry1);
CREATE INDEX IF NOT EXISTS game_e2 ON game(entry2);

CREATE TABLE IF NOT EXISTS game_player (
  game_id   TEXT NOT NULL REFERENCES game(id),
  entry_id  INTEGER NOT NULL REFERENCES entry(id),
  person_id INTEGER NOT NULL REFERENCES person(id),
  role      TEXT,
  is_skip   INTEGER NOT NULL DEFAULT 0,
  played    INTEGER,
  PRIMARY KEY (game_id, person_id)
);
CREATE INDEX IF NOT EXISTS game_player_person ON game_player(person_id);

-- Times do circuito profissional ao longo do tempo (a formação muda a cada temporada)
CREATE TABLE IF NOT EXISTS squad (
  id       INTEGER PRIMARY KEY,
  name     TEXT NOT NULL,             -- 'Team Hasselborg'
  gender   TEXT,
  nation   TEXT,
  season   TEXT NOT NULL,
  skip_id  INTEGER REFERENCES person(id),
  lineage  INTEGER                    -- id do primeiro squad da mesma linhagem
);
CREATE TABLE IF NOT EXISTS squad_member (
  squad_id  INTEGER NOT NULL REFERENCES squad(id),
  person_id INTEGER NOT NULL REFERENCES person(id),
  role      TEXT,
  PRIMARY KEY (squad_id, person_id)
);

-- Fotos com licença livre (Wikidata + Commons), ligadas pelo código da World Curling
CREATE TABLE IF NOT EXISTS photo (
  person_id   INTEGER PRIMARY KEY REFERENCES person(id),
  wcf_id      INTEGER,
  qid         TEXT,                   -- item do Wikidata
  file        TEXT NOT NULL,          -- arquivo no Commons
  path        TEXT NOT NULL,          -- site/img/people/<path>
  page        TEXT,                   -- página do arquivo no Commons (crédito)
  author      TEXT,
  license     TEXT,
  license_url TEXT,
  fetched_at  TEXT
);

-- Atalho: pessoa "viva" (resolve fusões de duplicatas)
CREATE VIEW IF NOT EXISTS person_live AS
  SELECT p.id AS raw_id, COALESCE(p.merged_into, p.id) AS id FROM person p;
"""


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    _migrate(con)
    return con


def _migrate(con: sqlite3.Connection) -> None:
    """Acrescenta colunas novas em bancos criados por versões anteriores."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(entry)")}
    if "club" not in cols:
        con.execute("ALTER TABLE entry ADD COLUMN club TEXT")
