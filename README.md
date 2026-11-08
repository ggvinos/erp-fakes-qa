# ERP Fakes QA

Simuladores de ERPs de saúde (Feegow, NetPacs e Tasy) para quem testa integrações. Sobe em um comando, responde como o ERP real, e deixa o QA controlar o que o ERP devolve: mudar um valor, cancelar ou remarcar um agendamento, fazer o ERP demorar, errar ou ficar fora do ar. Serve para validar integrações em ambientes de teste que não têm conta de ERP e como base para testes automatizados, sem depender de ERP de cliente.

Python 3.10 ou superior, sem dependências.

## Para que serve no dia a dia de QA

- Validar um card de integração sem conta real: você controla os dados do ERP e confere o que o sistema testado gravou.
- Reproduzir bug de integração: edite o dado no ERP, force a carga e veja o resultado, quantas vezes precisar, com a mesma massa.
- Testar caminhos que o ERP real raramente produz: valor zero, negativo ou fora do limite, convênio ainda não sincronizado, resposta vazia, erro 5xx, timeout, token inativo.
- Rodar testes automatizados (pytest, Cypress, qualquer cliente HTTP) contra um ERP determinístico.
- Gerar volume (até 100 mil pacientes e agendamentos) ou importar a sua própria massa em CSV ou JSON.

## Instalar

Linux e macOS, um comando:

```bash
curl -fsSL https://raw.githubusercontent.com/ggvinos/erp-fakes-qa/main/install.sh | sh
```

O instalador usa `pipx` se existir, ou cria um ambiente isolado em `~/.local/share/erp-fakes` e põe o comando `erp-fakes` em `~/.local/bin`. Baixa também o `cloudflared` oficial da Cloudflare, que cria o endereço público; para pular, use `ERP_FAKES_SEM_TUNEL=1`. Para remover: `./install.sh --remover`.

Em qualquer sistema, inclusive Windows:

```bash
pip install git+https://github.com/ggvinos/erp-fakes-qa.git
erp-fakes --instalar-tunel
```

Dentro de um clone, `python3 -m erp_fakes` também funciona.

## Começar

```bash
erp-fakes
```

1. O programa sobe os ERPs, abre o túnel e abre o painel em `http://localhost:8099/`.
2. Na tela Início, copie a URL e o token e cole na configuração de integração do sistema que você testa.
3. Dispare a carga de agendamentos no sistema testado e acompanhe em Chamadas o que ele pediu.

Sem túnel (testes locais e automatizados): `erp-fakes --no-tunnel`. O túnel gratuito da Cloudflare muda de URL a cada reinício; a tela avisa quando a URL cadastrada ficou desatualizada.

## Os ERPs

O mesmo programa simula três ERPs. O seletor no topo da barra lateral troca o ERP que você está editando; cada um tem dados, ids permanentes, chave de acesso, falhas e atalhos próprios, e todos usam o mesmo painel.

| ERP | Como o cliente fala com ele |
| --- | --- |
| Feegow | API REST, header `x-access-token`, segue a documentação oficial (https://docs.feegow.com/) |
| NetPacs | API REST `/netris/api/...`, header `Authorization` com a chave crua |
| Tasy (agente) | HTTP do agente `tasy-api`, JWT HS256 em `Authorization: Basic` |

Todos respondem no mesmo endereço: o fake escolhe o ERP pela rota (`/netris/...` é NetPacs, `/schedules` e `/client` são Tasy, o resto é Feegow). Não há documentação pública de NetPacs e Tasy: o contrato deles foi inferido do comportamento de um cliente real e não foi validado com carga real. A aba Documentação de cada ERP lista as rotas, o que o fake implementa e as diferenças conhecidas.

Pontos que mudam o resultado do teste:

- NetPacs: a resposta `[]` na carga faz o cliente cancelar tudo que estava na janela. O host do túnel não pode conter `v2`, porque a URL precisa terminar em `/v2`.
- Tasy: o agendamento pode trazer o campo `price`. Confirmar e cancelar só contam com a resposta de texto `OK`.

## O painel

Uma tela só, com navegação fixa. Ela só abre em `localhost`: pelo endereço público responde 404, então o token não vaza. O token é gerado na primeira execução e guardado em `~/.config/erp-fakes/state.json`, fora do repositório.

| Aba | Para que serve |
| --- | --- |
| Início | URL e token para cadastrar, avisos e a atividade recente do sistema testado |
| Dados | mapa de entidades e relacionamentos e edição de qualquer dado do ERP |
| Agendamentos | buscar agendamentos, agir como a recepção da clínica e criar agendamentos |
| Horários | horários livres por profissional, local e dia |
| Volume e importação | gerar volume, importar CSV ou JSON, exportar e prompt para pedir massa a uma IA |
| Roteiros | receitas prontas que mudam o ERP e conferem o resultado (aparece quando o perfil tem roteiros) |
| Chamadas | diário do que o sistema pediu, enviou, recebeu e quanto demorou |
| Falhas | fazer o ERP demorar, errar, responder vazio ou quebrado, ou derrubar a conexão |
| Documentação | rotas, quais o cliente usa, quais o fake implementa e as diferenças conhecidas |

**Avisos do Início:** URL desatualizada, token diferente (última chamada recusada com 401 ou 403), túnel fora do ar, falha simulada ativa e sem chamadas há 15 minutos.

**Agendamentos:** ações da clínica por botão: confirmar, cancelar, desmarcar pelo profissional, paciente chegou, atendido, faltou, remarcar (mantém o id), trocar profissional, convênio ou procedimento, definir valor e sumir do ERP. O novo agendamento aceita "daqui a N horas", útil para testar confirmação e lembretes com o seu telefone.

**Falhas:** atalhos prontos (ERP lento, fora do ar, chave inativa, horário ocupado, carga vazia) ou regra própria por rota, método, tipo e número de vezes. Cada chamada afetada aparece marcada no diário.

## Volume e importação

A tela Volume e importação serve para ter mais dados do que o padrão (600 pacientes, 1500 agendamentos, 40 profissionais).

- **Gerar volume:** acrescenta pacientes, profissionais e agendamentos, ou gera tudo de novo com os totais informados. Os ids novos são permanentes.
- **Importar:** cola JSON (uma lista por entidade) ou CSV (uma entidade por vez). "Validar sem alterar" mostra o que seria criado e os erros linha a linha. Os vínculos aceitam id ou nome exato. O modo "Substituir" apaga os dados atuais do ERP antes.
- **Exportar:** baixa tudo no mesmo formato da importação, para guardar uma massa e restaurar depois.
- **Prompt para IA:** texto pronto com as colunas e as regras de segurança para pedir dados a uma IA e importar o resultado.

Cuidado ao reduzir dados: se o sistema testado já carregou agendamentos que o fake deixa de servir, ele pode conferir um por um cada agendamento que sumiu, o que prende a conta por muito tempo com dezenas de milhares de registros. Prefira acrescentar.

Entidades, em ordem de dependência: `unidades`, `especialidades`, `convenios`, `procedimentos`, `profissionais`, `pacientes`, `agendamentos`. Pela API: `POST /_admin/volume`, `POST /_admin/importar`, `GET /_admin/exportar`, `GET /_admin/modelos`.

## Dados fictícios e seguros

Os dados são inventados e não coincidem com pessoas reais:

- **Telefone:** `554800` mais 7 dígitos, número que não existe, então ninguém recebe mensagem. A importação recusa qualquer outro, a menos que você marque "Permitir telefone real". Na linha de comando, `--phone` põe um telefone real nos primeiros pacientes, para você testar com o seu número.
- **CPF:** fictício com dígitos verificadores corretos. CPF informado na importação é conferido só no formato, e um aviso lembra de checar que não é de pessoa real.
- **E-mail:** sempre `@teste.invalid`, domínio reservado que nunca existe.
- **Nomes:** combinações de nomes comuns, sem relação com pessoas específicas.

Os testes cobrem isso. As datas são calculadas a cada requisição e nunca expiram. Os ids da carga inicial são fixos (agendamentos 900001 em diante, pacientes 5001 em diante); os criados depois recebem ids a partir de 910001 e 6001, e o último fica em `~/.config/erp-fakes/ids.json`, então reiniciar ou resetar nunca reaproveita um id que o sistema testado já guardou.

## Cenários

Cada agendamento carrega o cenário em `obs` (`cenario=...`).

| Cenário | O que testa |
| --- | --- |
| particular_com_valor_erp, particular_sem_valor_erp | valor do ERP e preço de tabela |
| convenio_com_valor_erp, convenio_sem_valor_erp | valor do ERP e regra de convênio |
| convenio_nao_sincronizado_com_valor | convênio que ainda não existe na lista de convênios |
| tabela_cartao_desconto | tabela com multiplicador 0,6 |
| valor_zero, valor_negativo, valor_acima_do_limite | valores que o cliente deve descartar |
| formatos_de_valor, valor_numerico_json | "R$ 1.234,56", "855", "432.50", número em JSON |
| multiplos_procedimentos | valor total com vários procedimentos |
| particular_sem_preco_tabela | tabela sem preço para o procedimento |

## Perfis e roteiros

O núcleo é neutro e não conhece o sistema que você testa. O que depende dele vem de um perfil, escolhido com `--perfil` ou `ERP_FAKES_PERFIL`:

- nome e vocabulário da tela;
- roteiros: receitas com passos (o que acontece no ERP) e verificações (o que se espera no sistema testado depois da carga);
- consulta SQL para conferir no banco do sistema testado os agendamentos pelo id externo;
- nomes dos status, rótulos dos campos de conta e notas do contrato.

Sem perfil, a aba Roteiros e o botão Conferir não aparecem, e o resto funciona igual. O perfil `exemplo` (`--perfil exemplo`) traz roteiros de preço, formatos de valor, troca de procedimento, ações da clínica e agendamento que some, com uma consulta e status hipotéticos. Para criar o seu, copie `erp_fakes/perfis/exemplo.py`, troque a consulta e os status pelos do seu sistema, e use `--perfil seu_pacote.seu_modulo`.

Como o roteiro funciona: você executa, o fake muda o ERP e devolve os IDs externos afetados e a consulta para o banco; você roda a carga no sistema testado, roda a consulta e cola o resultado; a tela marca cada verificação como passou, falhou ou não chegou. Também por código: `fake.run_script("preco-do-agendamento")` e `fake.evaluate(...)`.

## Usar em testes automatizados

O módulo `erp_fakes.testing` sobe o fake em uma porta livre, dentro do processo.

```python
from erp_fakes import FakeErp

with FakeErp() as fake:                       # FakeErp(erp="netpacs") ou erp="tasy"
    fake.url, fake.token                      # valores para a integração
    s = fake.schedules("particular_com_valor_erp")[0]
    fake.action(s["agendamento_id"], "definir_valor", valor="R$ 777,00")
    fake.action(s["agendamento_id"], "cancelar")
    fake.edit("profissionais", 2001, nome="Dr. Outro")
    fake.fault("/appoints/search", "status", 503, times=1)   # ERP com problema
    fake.get("/appoints/search", agendamento_id=s["agendamento_id"])
    fake.journal(so_erros=1)                  # o que foi pedido e o que voltou
    fake.reset()
```

Com pytest:

```python
import pytest
from erp_fakes import FakeErp

@pytest.fixture(scope="session")
def erp():
    with FakeErp(patients=100, schedules=300) as fake:
        yield fake
```

Com Cypress ou qualquer ferramenta externa, suba o servidor e chame por HTTP:

```bash
erp-fakes --no-tunnel --no-browser --port 8099 --token teste
```

```js
cy.request({ url: "http://localhost:8099/_admin/scenarios", headers: { "x-access-token": "teste" } });
```

Administração (token no header `x-access-token`): `/_admin/entities/<tipo>`, `/_admin/schedules`, `/_admin/schedule`, `/_admin/schedule/<id>/acao`, `/_admin/faults`, `/_admin/journal`, `/_admin/catalog`, `/_admin/model`, `/_admin/config`, `/_admin/scenarios`, `/_admin/insurance/sync` e `/_admin/reset`.

## Opções

| Opção | Padrão | Para que serve |
| --- | --- | --- |
| `--port` | 8099 | porta local |
| `--no-tunnel` | desligado | não abre túnel |
| `--existing-tunnel URL` | nenhum | usa um túnel já aberto por outro processo |
| `--no-browser` | desligado | não abre o navegador |
| `--token` | gerado | token fixo |
| `--seed` | 42 | semente dos dados (mesma semente, mesmos dados) |
| `--patients` / `--schedules` / `--days` / `--units` | 600 / 1500 / 14 / 3 | volume |
| `--phone` / `--phone-count` | nenhum / 5 | telefone real nos primeiros pacientes |
| `--cloudflared` | auto | caminho do binário do túnel |
| `--instalar-tunel` | | baixa o cloudflared e sai |
| `--perfil` | neutro | perfil do sistema testado |

## Desenvolvimento

```bash
python3 -m unittest discover -s tests -v
```

Os testes cobrem autenticação, o contrato da carga, os cenários, as escritas e seus erros, a administração, as falhas simuladas, o diário, o catálogo, os avisos, os ids novos, a segurança dos dados fictícios, os roteiros, os perfis e o instalador do túnel. Um teste de higiene falha se o código citar empresas, cards ou servidores internos.

```
erp_fakes/
  model.py      dados gerados e regras dos cenários
  handler.py    rotas HTTP, administração, diário e falhas
  erp_netpacs.py, erp_tasy.py   dialetos dos outros ERPs
  ops.py        edição de entidades e ações sobre agendamentos
  dados.py      volume, importação e exportação
  roteiros.py   motor dos roteiros
  perfil.py     contrato dos perfis
  perfis/       perfil de exemplo
  idstore.py    ids novos que nunca se repetem
  faults.py     motor de falhas simuladas
  catalog.py    rotas da documentação e diferenças conhecidas
  launcher.py   túnel, avisos e painel local
  tunel_bin.py  localiza e instala o cloudflared
  testing.py    FakeErp para testes
  app.html      painel
tests/
```

## Limites

- NetPacs e Tasy seguem o que um cliente real espera, sem documentação pública para conferir.
- Não valida o que o cliente envia além do necessário para o fluxo funcionar.
- O túnel gratuito da Cloudflare não tem garantia de estabilidade e a URL muda a cada reinício.
- Estado em memória: reiniciar volta aos dados iniciais (ids e chaves permanecem).
- Só simula Feegow, NetPacs e Tasy. Cada ERP novo segue o mesmo molde.

## Licença

MIT.
