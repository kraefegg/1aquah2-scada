# Passo a Passo: Publicar no GitHub

## O que você precisa

- Conta gratuita no GitHub (github.com)
- Git instalado no computador
- Os arquivos do AquaH2 extraídos

---

## PASSO 1 — Criar conta no GitHub (se não tiver)

1. Acesse https://github.com
2. Clique em **Sign up**
3. Escolha um username (ex: `kraefegg` ou `railson-dev`)
4. Confirme o email

---

## PASSO 2 — Instalar o Git

### Windows
Baixe em: https://git-scm.com/download/win  
Instale com as opções padrão.

### Mac
```bash
brew install git
# ou simplesmente abra o terminal e digite:
git --version
# o Mac oferecerá instalar automaticamente
```

### Linux
```bash
sudo apt install git        # Ubuntu/Debian
sudo dnf install git        # Fedora
```

---

## PASSO 3 — Configurar seu nome no Git (uma vez só)

Abra o terminal e execute:

```bash
git config --global user.name "Railson"
git config --global user.email "seu@email.com"
```

---

## PASSO 4 — Criar o repositório no GitHub

1. Acesse https://github.com/new
2. Preencha:
   - **Repository name:** `aquah2-scada`
   - **Description:** `AI-SCADA platform for green hydrogen production + SWRO desalination`
   - **Visibility:** Public (para aparecer nas buscas) ou Private
   - **NÃO** marque "Initialize this repository"
3. Clique em **Create repository**
4. Copie a URL que aparece (ex: `https://github.com/railson-dev/aquah2-scada.git`)

---

## PASSO 5 — Organizar os arquivos na pasta correta

Certifique-se que sua pasta `AquaH2` tem esta estrutura:

```
AquaH2/
├── run.py
├── aquah2_platform.html
├── README.md           ← copie do ZIP entregue
├── .gitignore          ← copie do ZIP entregue
├── LICENSE             ← copie do ZIP entregue
├── CONTRIBUTING.md     ← copie do ZIP entregue
├── docs/
│   ├── api.md
│   └── hardware.md
├── .github/
│   ├── workflows/
│   │   └── test.yml
│   └── ISSUE_TEMPLATE/
│       ├── bug_report.md
│       └── feature_request.md
└── backend/            ← opcional (módulos independentes)
    ├── simulator.py
    ├── ai_engine.py
    ├── database.py
    ├── config.py
    ├── main.py
    ├── test_system.py
    └── requirements.txt
```

---

## PASSO 6 — Publicar no GitHub

Abra o terminal **dentro da pasta AquaH2** e execute os comandos em sequência:

```bash
# 1. Inicializar o repositório Git local
git init

# 2. Adicionar todos os arquivos
git add .

# 3. Criar o primeiro commit
git commit -m "feat: initial release — AquaH2 AI-SCADA v2.1.4"

# 4. Renomear a branch para 'main'
git branch -M main

# 5. Conectar ao repositório remoto (substitua a URL pela sua)
git remote add origin https://github.com/SEU-USUARIO/aquah2-scada.git

# 6. Enviar para o GitHub
git push -u origin main
```

**Autenticação:** o Git pedirá seu usuário e senha do GitHub.  
Se aparecer erro de autenticação, use um Personal Access Token:
1. GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Gere um token com permissão `repo`
3. Use o token no lugar da senha

---

## PASSO 7 — Verificar no GitHub

1. Acesse `https://github.com/SEU-USUARIO/aquah2-scada`
2. Você verá todos os arquivos listados
3. O README.md aparece automaticamente formatado na página inicial
4. A aba **Actions** mostrará os testes rodando automaticamente

---

## PASSO 8 (opcional) — Adicionar tópicos e descrição

Na página do repositório:
1. Clique na engrenagem ⚙️ ao lado de **About**
2. Adicione:
   - Description: `AI-SCADA platform for green hydrogen production + SWRO desalination`
   - Topics: `scada`, `hydrogen`, `python`, `iot`, `ai`, `industrial-automation`, `modbus`, `opc-ua`
3. Clique em **Save changes**

---

## Atualizar o repositório depois de modificações

```bash
# Após modificar arquivos:
git add .
git commit -m "feat: descrição do que mudou"
git push
```

---

## Dicas finais

- O arquivo `aquah2_data.db` está no `.gitignore` — dados de produção **não** vão para o GitHub
- Nunca versione sua `ANTHROPIC_API_KEY` — mantenha em variável de ambiente
- Use `git status` para ver o que está pendente de commit
- Use `git log --oneline` para ver o histórico de commits
