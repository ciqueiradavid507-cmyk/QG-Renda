# Manutenção automática do QG RENDA

O portal mantém um catálogo de **sete fontes oficiais permitidas**. A rotina verifica essas fontes e atualiza os metadados que o site apresenta: título, descrição disponível na origem, disponibilidade, código HTTP e datas de checagem, de sucesso e de alteração. Se a origem não fornecer uma descrição utilizável, permanece a descrição editorial identificada como tal.

Os passos e as orientações autorais dos guias continuam sob revisão do responsável pelo projeto. A rotina não reescreve esses textos, não publica código, não cria contas ou pagamentos e não transforma o QG RENDA em órgão público nem em parceiro reconhecido do governo.

## Como a rotina é executada

O backend usa um intervalo de atualização de seis horas. Uma consulta a `/api/automation?wait=true` aguarda a checagem necessária ou uma checagem que já esteja em andamento. Se a última checagem ainda estiver válida, reutiliza o resultado; não é um comando para forçar atualizações ilimitadas.

O workflow `.github/workflows/manutencao-portal.yml` consulta esse endpoint público a cada seis horas, no minuto 17: `17 */6 * * *`. O agendamento usa UTC. Em **America/Belem (UTC−3)**, os horários previstos são **03h17, 09h17, 15h17 e 21h17**. A consulta também pode acordar uma instância ociosa do Render, sem criar um serviço de cron adicional.

O GitHub executa o agendamento a partir da **branch padrão `main`**. Por isso, o arquivo do workflow precisa existir nessa branch, mesmo que o serviço Render publique o código da branch `qg-renda-v2-original`. O workflow e seus relatórios mensais ficam em `main`; não é necessário copiar para lá o código do portal.

Também é possível iniciar a rotina em **Actions → Manutenção das fontes do portal → Run workflow**. Uma atualização do próprio arquivo do workflow em `main` dispara uma execução, permitindo verificar a primeira instalação após a publicação do backend. Atualizações de outros arquivos não disparam essa execução por `push`.

## O que a verificação confirma

A execução passa quando o backend confirma:

- automação habilitada, sem erro global de atualização e sem checagem ainda em andamento;
- `last_checked_at` preenchido, em formato ISO com fuso horário, e com até oito horas de idade;
- sete fontes no catálogo e sete resultados na resposta;
- contagens válidas de fontes disponíveis, indisponíveis e alteradas.

Uma fonte individual temporariamente indisponível **não faz o workflow falhar**. Essa condição aparece nas contagens e no estado da própria fonte. Quando existe uma versão válida anterior no cache, o backend a preserva; a indisponibilidade atual continua visível. Erro global do backend, resposta inválida ou ausência de uma checagem recente fazem a execução falhar após tentativas limitadas.

O workflow tem quatro tentativas de rede, com limite de 45 segundos por chamada e pausas de 5, 10 e 20 segundos. O job inteiro tem limite de cinco minutos. Usa apenas Python da biblioteca padrão, sem instalar dependências. As execuções desse workflow são serializadas para evitar sobreposição. Os logs mostram somente contagens, horário de checagem e códigos de falha controlados; não imprimem respostas completas, consultas de usuários, endereços de fontes ou dados pessoais.

## Relatório mensal de manutenção

Após uma checagem válida, a rotina consulta o período do relatório `reports/portal-maintenance.json` na branch `main`. Na primeira execução, cria esse arquivo. Depois, ele só é atualizado na primeira execução válida de um **novo mês em America/Belem**. As demais checagens do mês não alteram arquivos nem criam commits. As versões anteriores do relatório permanecem no histórico Git desse arquivo.

O relatório contém dados públicos da manutenção: mês de referência, horário do registro, horário da última checagem, contagens e, para cada fonte, identificador, endereço canônico, título, disponibilidade e data do último sucesso. Queries e fragmentos são removidos dos endereços registrados. Não são incluídos conversas de atendimento, consultas de visitantes, e-mails, documentos ou outros dados pessoais.

Para gravar esse registro, o workflow faz checkout de `main` com `actions/checkout@v4` e recebe somente a permissão `contents: write` do `GITHUB_TOKEN` padrão. Não exige segredo adicional. O commit usa a identidade estática `github-actions[bot]` e inclui exclusivamente `reports/portal-maintenance.json`. Não há commit vazio, push forçado ou alteração de outros arquivos. A gravação deve respeitar as permissões e proteções da branch; a rotina não modifica essas regras para conseguir publicar.

Esse relatório é uma trilha de manutenção real, e não uma atualização do código ou dos textos do portal. O serviço Render usa a branch `qg-renda-v2-original`, separada de `main`, e a rotina não aciona deploys nem muda a configuração do serviço. O relatório também não está no filtro de arquivos do evento `push` deste workflow.

## Cache e continuidade

O backend grava um cache JSON local de forma atômica em `/tmp`. Ele ajuda a preservar o último conteúdo válido enquanto os arquivos da instância estiverem disponíveis. **Não é armazenamento persistente contratado:** reinícios, novos deploys ou substituição da instância podem perder o cache. Nesse caso, o catálogo editorial inicial é carregado e as fontes voltam a ser verificadas. Não há promessa de retenção indefinida da última versão válida nesse cache. Os relatórios mensais já gravados no histórico Git são independentes do cache da aplicação.

O agendamento do GitHub é **best effort**: pode atrasar e, em períodos de carga alta, algumas execuções podem ser descartadas. Não há garantia de execução no segundo exato. O minuto 17 evita o começo da hora, indicado pela documentação como um período comum de maior carga.

Além disso, o GitHub desativa workflows agendados em repositórios públicos após **60 dias sem atividade no repositório**. O relatório mensal registra trabalho útil, sem commits vazios. Contudo, a documentação oficial consultada não esclarece se commits de `github-actions[bot]` com `GITHUB_TOKEN` reiniciam esse contador de inatividade. O relatório não é uma garantia de impedir a desativação. Se o agendamento for desativado, o proprietário precisa reativá-lo na página de Actions e verificar uma execução manual. Portanto, a configuração não garante manutenção indefinida sem eventual intervenção do responsável.

## Custos e referências

O workflow usa o runner padrão `ubuntu-latest`. Conforme a documentação do GitHub, runners hospedados padrão são gratuitos em repositórios públicos; *larger runners* têm cobrança inclusive nesses repositórios e não são usados aqui. Não foi criado serviço adicional no Render nem alterado o plano de hospedagem.

Referências oficiais consultadas em 14 de novembro de 2026:

- [Eventos `schedule` e suas limitações](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
- [Execução manual com `workflow_dispatch`](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch).
- [Desativação e reativação de workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows).
- [Eventos gerados por um workflow e o `GITHUB_TOKEN`](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow#triggering-a-workflow-from-a-workflow): a regra de prevenção de recursão não define o contador de inatividade dos agendamentos.
- [Cobrança do GitHub Actions e tipos de runner](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
