# WhatsApp Comercial — versão revisada

Aplicativo Python com Tkinter e Selenium, baseado no código fornecido. Mantém o Chrome e uma única guia do WhatsApp Web durante a fila.

## Executar

É necessário Python 3.10 ou superior, Google Chrome instalado e uma sessão gráfica no computador. Na pasta dos arquivos, execute:

```bash
python -m pip install -r requirements.txt
python disparador.py
```

Em alguns computadores, o comando é `python3`. No Linux, pode ser necessário instalar o pacote `python3-tk` pelo gerenciador do sistema. O Selenium gerencia o driver do Chrome; a primeira execução pode precisar baixar o driver.

1. Informe os telefones com DDI e DDD, um por linha, por exemplo `+55 (11) 99999-0000`. Duplicados são removidos. O programa não adivinha nem acrescenta o DDI e não confirma se o número existe.
2. Preencha a mensagem, os intervalos positivos e, opcionalmente, uma imagem PNG ou JPEG.
3. Clique em **Iniciar / Continuar**. O programa inicia o envio assim que o WhatsApp carregar. Na primeira vez, escaneie o QR Code no Chrome aberto pelo aplicativo.
4. **Pausar** interrompe esperas e impede o próximo envio. Uma navegação ou operação do navegador em andamento pode precisar terminar. Se o envio já foi tentado, o programa aguarda a verificação local antes de pausar.
5. **Continuar** retoma os contatos pendentes. Os dados da fila ficam travados até clicar em **Nova fila**. Isso mantém a mesma mensagem e os mesmos destinatários na retomada.
6. Exporte o CSV antes de clicar em **Nova fila** ou fechar: o histórico e o progresso ficam apenas na memória nesta versão.

Não utilize manualmente a guia automatizada durante a execução. O aplicativo substitui rascunhos na conversa de destino ao preparar a mensagem. Abra apenas uma instância por vez, pois o perfil do Chrome é exclusivo.

## O que mudou

- O caminho `wa.me → Iniciar conversa → WhatsApp Web` foi substituído por `https://web.whatsapp.com/send?phone=...`, usando `driver.get()` na guia original. Não são criadas guias adicionais pelo aplicativo. **A navegação recarrega a página para cada contato.** Trocar de conversa sem recarregar exigiria automatizar a interface de nova conversa, com mais dependência dos seletores e do idioma do WhatsApp.
- Removidos os cliques em páginas intermediárias, a tentativa de abrir o aplicativo externo e as pausas fixas nesses passos.
- O STOP/PLAY original reabilitava o PLAY antes de o thread antigo terminar. Agora uma nova execução só começa após o término e o processamento dos resultados da anterior.
- Todas as mudanças na interface ocorrem no thread principal. O worker usa uma fila de eventos, sem acessar o Tkinter diretamente.
- Telefones são normalizados e deduplicados; letras, entradas malformadas e intervalos negativos ou zero são rejeitados.
- O programa verifica o aparecimento de uma mensagem de saída no DOM em vez de presumir sucesso depois de três segundos. Isso indica apenas **saída local**, não entrega ao destinatário nem leitura.
- Falhas ficam visíveis no histórico e no CSV. A fila para na primeira falha ou resultado incerto para evitar repetir uma operação ou avançar por todos os contatos com uma sessão quebrada.
- A captura de erros não usa a variável de exceção em uma função agendada para depois, um problema presente no código original.
- A sessão é mantida em `sessao_whatsapp`, ao lado do script. Proteja essa pasta: ela contém os dados de login. Não compartilhe nem inclua essa pasta no ZIP.

## Resultados e retomada

| Status | Significado |
| --- | --- |
| `saida_local` | Uma nova mensagem de saída apareceu na conversa. Entrega não verificada. |
| `falha` | Ocorreu um erro antes da tentativa de envio. |
| `incerto` | O envio pode ter ocorrido, mas a verificação local falhou. Confira a conversa antes de repetir. |

Um contato com resultado registrado é considerado processado. Ao continuar após uma falha ou resultado incerto, o programa segue para o próximo contato. Para tentar o contato anterior novamente, confira o WhatsApp, exporte o relatório e prepare uma nova fila somente com os contatos desejados. Não há repetição automática.

## Validação e limites

Os testes usam navegador e campos simulados; cobrem a navegação na mesma guia, normalização, rascunhos, pausa, retomada, falhas e resultados incertos:

```bash
python -m unittest -v
```

O envio real, o login e os seletores atuais do WhatsApp **não foram validados em uma conta conectada**. Antes de usar com a equipe, teste texto, mensagem com quebras de linha e imagem com um destinatário de teste. Os seletores do WhatsApp Web podem mudar, especialmente os do anexo e da legenda em português/inglês. Emojis fora do BMP podem não ser aceitos pelo `send_keys` de algumas versões do ChromeDriver.

O link de navegação é público, mas a automação por Selenium não é a API oficial de mensagens. Os intervalos são apenas controle de ritmo, sem garantia contra restrições da plataforma. Para operação comercial de maior escala, considere a WhatsApp Business Platform e destinatários que aceitaram receber mensagens.
