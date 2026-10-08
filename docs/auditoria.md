# Auditoria do banco — 8 de outubro de 2026

Banco: 543 campeonatos da World Curling (1959–2026), 32.019 jogos, 7.290 participações de times.
Comando para repetir: `python3 -m hc audit`.

## 1. Regras verificadas em todos os registros

| Regra | Verificados | OK | Observação |
|---|---:|---:|---|
| Jogo com dois times diferentes e placar dos dois lados | 32.019 | 99,80% | 63 jogos sem placar de um lado, publicados assim pela fonte |
| Placar total = soma dos ends | 28.574 | 99,59% | 117 divergências na própria fonte, quase todas antes de 2000 |
| Só um time pontua por end | 240.541 ends | 99,99% | 34 ends com pontos dos dois lados, erro de digitação na fonte |
| Hammer coerente | 25.243 | 100% | quem tem o hammer pontua em 68–73% dos ends com pontos, em todas as décadas (padrão do esporte) |
| Campanha da classificação = jogos gravados | 7.287 | 96,45% | diferenças explicadas por jogos sem placar na fonte |
| Atleta em um só time por campeonato | 31.694 | 100% | 1 caso na fonte (Mihail Mardare, 2011) |
| Um skip por time; duplas mistas com 1 homem e 1 mulher | 7.284 | 99,41% | casos antigos sem skip marcado na fonte |
| Campeonato com medalha tem um campeão e um vice | 365 | 100% | |
| Data do jogo dentro do período do evento | 25.116 | 98,80% | erros de digitação de data na fonte (ex.: ano trocado) |

### Defeitos encontrados no nosso código e corrigidos

1. **Times duplicados em campeonatos antigos.** A fonte escreve "Canada , Regina CC, Saskatchewan" na
   classificação e "Canada" nos jogos. Gravávamos como dois times, o que fazia 26% dos atletas aparecerem
   em dois times no mesmo campeonato. Corrigido (o clube agora fica em `entry.club`), com teste.
2. **Duas "finais" no mesmo campeonato.** Alguns Europeus trazem a Divisão B na mesma página, e nos
   qualificatórios o "Silver game" decide a segunda vaga. Agora só é final o jogo entre times do topo da
   classificação, e o "Silver game" conta como fase final, não como final.

Os erros da fonte não são "corrigidos" por nós: o banco reflete o que a World Curling publica.

## 2. Amostragem contra fonte independente (Wikipedia)

Campeonatos sorteados (semente 2026) e alguns escolhidos por interesse (Itália):

| Campeonato | Pódio | Final | Resultado |
|---|---|---|---|
| Mundial Júnior feminino 2004 | NOR, CAN, SWE | Noruega 9–6 Canadá | confere |
| Europeu feminino 2010 | SWE, SCO, SUI | Suécia 8–6 Escócia | confere |
| Mundial feminino 1984 | CAN, SUI, GER | Canadá 10–0 Suíça | confere* |
| Mundial feminino 1998 | SWE, DEN, CAN | Suécia 7–3 Dinamarca | confere |
| Europeu masculino 1980 | SCO, NOR, SWE | Escócia 6–4 Noruega | pódio confere; placar diverge** |
| Mundial de duplas mistas 2022 | SCO, SUI, GER | Escócia 9–7 Suíça | confere |
| Olimpíadas 2026, masculino | CAN, GBR, SUI | Canadá 9–6 Grã-Bretanha | confere |
| Olimpíadas 2022, duplas mistas | ITA, NOR, SWE | Itália 8–5 Noruega | confere, inclusive end a end |

\* Em 1984 não houve disputa de 3º lugar; a World Curling classifica a Alemanha em 3º.
\** A Wikipedia diz 7–4, citando a própria página da World Curling, que diz 6–4 com ends somando 6–4.
Mantemos o dado oficial.

## 3. Identidade de atletas

- Toda pessoa é ancorada no código oficial da World Curling (9.836 fichas).
- 45 nomes apareciam com dois códigos diferentes. A World Curling quase nunca publica a data de nascimento,
  então a unificação usa também os companheiros de time: mesmo nome + mesma seleção + 2 ou mais colegas em
  comum (comparados pelo nome, porque às vezes o time inteiro ganha códigos novos) + nunca no mesmo evento.
- Resultado: 22 fichas unificadas (ex.: o time japonês de Seiji Yamamoto, que trocou de códigos em 2026),
  1 par confirmado como pessoas diferentes pela data de nascimento, 22 pares deixados para revisão humana
  (seleções diferentes ou evidência insuficiente, como "Jim Wilson" do Canadá, dos EUA e da Inglaterra).
- Cada unificação fica registrada com a justificativa na tabela `link` e pode ser desfeita.
