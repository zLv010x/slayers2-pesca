# Slayers 2 • Pesca

Macro de pesca automática para o Slayers 2 (Roblox), com aviso no Discord de cada item pego.

## Instalar (uma vez)

1. Instale o Python 3.12 ou mais novo em https://www.python.org/downloads/ e marque **"Add python.exe to PATH"**.
2. Dê dois cliques em `Instalar.bat` e espere terminar.

## Primeira vez

1. No Roblox: desligue **Screen Shake** e **Shift Lock**, equipe a vara e posicione a câmera como quer pescar.
   Deixe o jogo em **tela cheia** (ou maximizado).
2. Abra `Iniciar.bat`.
3. Aba **Configurar**:
   - **Marcar ponto**: clique na água onde a vara deve lançar. A câmera (bússola) fica gravada junto.
     Mudou de lugar ou de câmera? Marque de novo.
   - **Tecla da vara**: o número do slot da vara na hotbar.
   - **Ajustar área**: a caixa roxa tem que ficar em cima da **barra vertical do minigame** (lado direito
     da tela). Confira na primeira vez, porque a posição muda conforme o tamanho da tela.
     Arraste e clique em **Salvar**.
4. Aba **Discord** (opcional): cole o link do webhook e o seu ID para ser marcado nos itens raros.
5. Aperte **F1** (ou o atalho que você escolher) para começar e parar.

Na primeira vez que você iniciar, a macro abre o menu do jogo (tecla **M**) sozinha para contar as iscas.

## Achou um bug ou deixou rodando a noite toda?

Na aba **Sessão**, clique em **Exportar**. Abre a pasta `logs_para_enviar` com um arquivo
`slayers2-logs-....zip`: é só mandar esse arquivo. Ele **não** leva o link do seu webhook nem o seu ID.

## O que a macro faz sozinha

- Confere se a vara está na mão antes de lançar e só aperta a tecla da vara quando precisa.
- Pausa se o Roblox sair da frente ou se a câmera girar, e volta quando estiver tudo certo.
- Se algo der errado (vara não equipa, vários lançamentos sem peixe, erro inesperado), avisa no
  Discord, espera e tenta de novo. Só desiste depois de várias falhas seguidas sem pegar nada.
- Registra tudo em `logs/macro.log`, salva um print em `logs/evidencias/` quando algo dá errado e
  recortes da barra dos primeiros minigames em `logs/minigame/` (para ajustar o minigame).
- Não deixa o PC dormir nem a tela apagar enquanto está pescando.
- Conta as iscas, estima quanto tempo duram e troca sozinha quando a equipada acaba
  (Fish Head → Drowned Lure → Worm). Sem isca: avisa e continua pescando.
- Guarda tudo o que pegou em `logs/sessao-*.csv`.
- Usa um **catálogo de itens** para saber se um item já é conhecido, corrigir erros de leitura
  do nome e confirmar a raridade:
  - `catalogo/` é o catálogo **compartilhado**, que vem junto com a macro. Ela só lê essa pasta.
  - `catalogo_local/` é o **seu**: itens que ainda não estão no compartilhado entram aqui
    (uma imagem por item, sem repetir), junto com as suas contagens.
  - Item que não está em nenhum dos dois aparece no Discord como "Primeira vez no catálogo".
  - Se um nome entrar errado, corrija o `"name"` no `itens.json` e ponha a leitura errada em `"aliases"`.

## Atalhos

Todos podem ser trocados em **Configurar → Atalhos**. Os padrões são: F1 (iniciar e parar), F2 (marcar o ponto) e F3 (fechar).

## Privacidade

O `config.json` guarda o link do webhook, que funciona como uma senha. Não mande esse arquivo para ninguém.
Para mandar logs, use o botão **Exportar** (ele tira o link sozinho).
