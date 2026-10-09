# Hello, Curling

Um jeito fácil de acompanhar o curling. Este repositório guarda a parte de dados: o robô que lê as fontes
oficiais, o banco com atletas, seleções, campeonatos e jogos, e a exportação para o site.

Usa só a biblioteca padrão do Python (3.11 ou mais novo). Não há nada para instalar.

## Comandos

```bash
python3 -m hc sync-wcf                      # baixa todos os campeonatos da World Curling (1959 até hoje)
python3 -m hc sync-wcf --types 1,22 --since 2020   # só alguns tipos/anos
python3 -m hc sync-schedule                 # calendário automático: torneios atuais e próximos, com tabelas e placares
python3 -m hc photos                        # fotos livres dos atletas (Wikidata + Wikimedia Commons)
python3 -m hc persons --nations BRA,ITA     # lê as páginas pessoais (nascimento, gênero, seleções)
python3 -m hc dupes                         # procura a mesma pessoa cadastrada com dois códigos
python3 -m hc review                        # mostra os casos duvidosos que precisam de um humano
python3 -m hc overrides                     # aplica as decisões de data/overrides.toml
python3 -m hc stats                         # números do banco
python3 -m hc export                        # gera site/data/*.json
python3 -m unittest discover -s tests       # testes
```

O robô é educado com o site de origem: no máximo uma página por segundo, e guarda uma cópia local de tudo
(`data/raw/`). Campeonatos encerrados nunca são baixados de novo.

## Organização

```
hc/
  fetch.py         baixador com cache e limite de velocidade
  dom.py           leitor de HTML (biblioteca padrão)
  sources/wcf.py   leitores das páginas da World Curling
  ingest.py        grava no banco o que os leitores extraíram
  identity.py      liga corretamente quem é quem (ver abaixo)
  names.py         normalização e comparação de nomes
  export.py        gera os JSON do site
  db.py            esquema do banco SQLite
data/
  hello_curling.sqlite   o banco (fora do git; a versão oficial fica anexada à release "banco" no GitHub)
  overrides.toml         decisões manuais de identidade
tests/             testes com páginas reais salvas em tests/fixtures
worker/            api.hellocurling.com (Cloudflare Worker): repassa o placar ao vivo do Grand Slam; publicar com worker/deploy.sh
```

## Como ligamos quem é quem

O mesmo atleta aparece de formas diferentes em cada fonte: "Florian KRAMLINGER", "Kramlinger Florian",
"F. Kramlinger". Uma atleta muda de sobrenome ao casar. O Marc Pfister jogou pela Suíça e hoje joga pelas
Filipinas. Os times do Grand Slam levam só o sobrenome do skip ("Team Schwaller" pode ser o Yannick ou a Xenia).

A solução usa evidências em camadas, da mais forte para a mais fraca:

1. **Código oficial da World Curling como âncora.** Toda pessoa que já disputou um campeonato da World Curling
   tem um código único. Ele vira a identidade dela aqui. Grafias novas viram apelidos da mesma pessoa.
2. **Decisões manuais** em `data/overrides.toml`, que sempre vencem.
3. **Ligação automática com nota** para fontes sem código. Cada candidato é avaliado por:
   nome (contra todas as grafias já vistas), gênero (diferente elimina), seleção, tempo sem jogar e,
   principalmente, **companheiros de time em comum**: homônimos quase nunca têm os mesmos colegas.
   Só liga sozinho com nota ≥ 0,90 e vantagem ≥ 0,10 sobre o segundo candidato.
4. **Fila de revisão** para todo o resto. Nada duvidoso é ligado em silêncio.
5. **Duplicatas dentro da World Curling** (dados antigos montados por voluntários): só fundimos sozinhos
   quando nome e data de nascimento coincidem e as duas fichas nunca aparecem no mesmo evento.

Toda ligação fica registrada na tabela `link`, com método e confiança, e pode ser auditada ou desfeita.

## Fontes

| Fonte | Situação |
|---|---|
| World Curling, resultados históricos | lida: campeonatos, escalações, jogos com placar por end, fichas pessoais |
| World Curling, placar ao vivo (CURLIT) | lida: calendário de todos os torneios atuais e próximos; o site lê o placar ao vivo direto da API oficial |
| Wikidata + Wikimedia Commons | fotos com licença livre, ligadas pelo código oficial do atleta |
| Grand Slam of Curling | lida: calendário e resultados pelo robô; placar ao vivo pelo nosso serviço em api.hellocurling.com |
| CurlingZone | só com autorização |
