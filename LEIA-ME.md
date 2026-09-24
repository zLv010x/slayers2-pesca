# Slayers 2 • Pesca

Macro de pesca automática para o Slayers 2 (Roblox), com aviso no Discord de cada item pego.

## Instalar (uma vez)

1. Instale o Python 3.12 ou mais novo em https://www.python.org/downloads/ e marque **"Add python.exe to PATH"**.
2. Dê dois cliques em `Instalar.bat`.

## Usar

1. No Roblox: desligue **Screen Shake** e **Shift Lock**, equipe a vara e posicione a câmera como quer pescar.
2. Abra o **Iniciar** (o atalho com a logo do peixe, criado pelo `Instalar.bat`). Se ele não aparecer, use o `Iniciar.bat`.
3. Aba **Configurar**:
   - **Marcar ponto**: clique na água onde a vara deve lançar. A câmera (bússola) fica gravada junto.
   - **Tecla da vara**: o número do slot da vara na hotbar.
   - **Ajustar área**: só se a barra do minigame não for detectada.
4. Aba **Discord** (opcional): cole o link do webhook e o seu ID para ser marcado nos itens raros.
5. Aperte **F1** (ou o atalho que você escolher) para começar e parar.

## O que a macro faz sozinha

- Confere se a vara está na mão antes de lançar e só aperta a tecla da vara quando precisa.
- Pausa se o Roblox sair da frente ou se a câmera girar, e volta quando estiver tudo certo.
- Se algo der errado (vara não equipa, vários lançamentos sem peixe, erro inesperado), avisa no
  Discord, espera e tenta de novo. Se desistir depois de várias falhas seguidas, **reinicia sozinha**
  depois de 5 min (até 3 vezes por hora; muda em **Avançado**).
- Se você mexer no mouse bem na hora do lançamento, ela espera o mouse ficar livre e lança de novo.
- Se o jogo voltar para o **menu principal** (servidor reiniciou ou você caiu), ela para, avisa no
  Discord e não fica tentando: entre de novo, volte ao ponto de pesca e aperte F1.
- **Overlay** por cima do jogo com o tempo de macro, o total de cada peixe e item e as iscas gastas.
  Fica em cima da party; com a pesca parada dá para arrastar. Liga/desliga e "Voltar para a party"
  em **Configurar → Janela**. Ele não aparece nos prints da macro e, pescando, o clique passa através dele.
- Registra tudo em `logs/macro.log` e salva um print em `logs/evidencias/` quando algo dá errado.
- Não deixa o PC dormir nem a tela apagar enquanto está pescando.
- Guarda tudo o que pegou em `logs/sessao-*.csv`.
- Usa um **catálogo de itens** para saber se um item já é conhecido, corrigir erros de leitura
  do nome e confirmar a raridade:
  - `catalogo/` é o catálogo **compartilhado**, que vem junto com a macro. Ela só lê essa pasta.
  - `catalogo_local/` é o **seu**: itens que ainda não estão no compartilhado entram aqui
    (uma imagem por item, sem repetir), junto com as suas contagens.
  - Item que não está em nenhum dos dois aparece no Discord como "Primeira vez no catálogo".
  - Para mandar os itens novos para o compartilhado: `python src/catalog.py publicar`.
  - Se um nome entrar errado, corrija o `"name"` no `itens.json` e ponha a leitura errada em `"aliases"`.

## Atalhos

Todos podem ser trocados em **Configurar → Atalhos**. Os padrões são: F1 (iniciar e parar), F2 (marcar o ponto) e F3 (fechar).

## Privacidade

O `config.json` guarda o link do webhook, que funciona como uma senha. Não mande esse arquivo para ninguém. Se for passar a macro para alguém, passe a pasta sem o `config.json`.

---
A detecção da barra do minigame foi portada da macro original do 1vtt (youtube.com/@1-vtt).
