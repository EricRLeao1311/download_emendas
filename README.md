# Baixador de Emendas Parlamentares

Aplicacao web local feita com `Python + HTML + CSS + JavaScript` para explorar os parquets de emendas parlamentares, escolher colunas, aplicar filtros e exportar o resultado em CSV ou Excel.

## O que ja vem pronto

- selecao entre base de `Emendas` e base de `Documentos`
- filtros dinamicos com busca parcial nas opcoes
- limite configuravel de linhas e colunas para download
- exportacao em `CSV` e `XLSX`
- acesso por token para abrir a pagina e baixar arquivos
- script para converter os CSVs brutos em parquet
- script para gerar novos tokens
- layout branco/azul com preview em tabela compacta e scroll proprio

## Estrutura

- `app.py`: aplicacao web ASGI
- `launch.py`: sobe o servidor local com `python launch.py`
- `templates/index.html`: pagina principal
- `templates/login.html`: tela de acesso por token
- `static/app.css`: visual da aplicacao
- `static/app.js`: interacoes no navegador
- `config/app.toml`: caminhos dos arquivos, limites e configuracao de autenticacao
- `config/access_tokens.json`: hashes dos tokens cadastrados
- `scripts/update_parquets.py`: atualiza os parquets a partir dos CSVs
- `scripts/manage_tokens.py`: cria e lista tokens de acesso
- `src/download_emendas/`: regras de configuracao, consulta, exportacao e autenticacao

## Situacao atual dos dados

Os dois parquets completos ja foram gerados:

- `emendas.parquet`: `92.755` linhas
- `documentos.parquet`: `4.342.775` linhas

Os caminhos iniciais dos CSVs continuam apontando para:

- `C:/Users/Eric/Downloads/Atualizar_emendas/Atualizar_emendas/out/emendasgeral13052026.csv`
- `C:/Users/Eric/Downloads/Atualizar_emendas/Atualizar_emendas/out/emendinhas13052026.csv`

Se quiser trocar limites ou caminhos, edite [config/app.toml](/C:/Users/Eric/Documents/GitHub/download_emendas/config/app.toml).

## Atualizando os parquets

Atualiza os dois datasets usando os caminhos do `config/app.toml`:

```powershell
& 'C:\Users\Eric\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\update_parquets.py
```

Atualiza so uma base:

```powershell
& 'C:\Users\Eric\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\update_parquets.py --only documentos --threads 1
```

Usa caminhos informados na linha de comando:

```powershell
& 'C:\Users\Eric\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\update_parquets.py `
  --emendas-csv 'C:\caminho\emendas.csv' `
  --documentos-csv 'C:\caminho\documentos.csv'
```

## Abrindo a interface

```powershell
& 'C:\Users\Eric\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' launch.py
```

Depois abra `http://127.0.0.1:8501`.

Se quiser subir em outra porta:

```powershell
$env:PORT='8503'
& 'C:\Users\Eric\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' launch.py
```

## Teste publico rapido com Cloudflare Tunnel

Se quiser compartilhar uma URL publica temporaria para teste:

1. Suba o app localmente.
2. Se necessario, use outra porta:

```powershell
$env:PORT='8503'
& 'C:\Users\Eric\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' launch.py
```

3. Em outro terminal, abra o tunel:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_quick_tunnel.ps1 -Port 8503
```

4. Copie a URL `trycloudflare.com` exibida no terminal.

Para encerrar o tunel:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop_quick_tunnel.ps1
```

## Tokens de acesso

O acesso fica protegido por token. A tela principal redireciona para `/login` quando o cookie ainda nao existe ou quando o token ficou invalido.

Gera um novo token:

```powershell
& 'C:\Users\Eric\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\manage_tokens.py create --label 'Meu token'
```

Lista os tokens cadastrados sem exibir o valor bruto:

```powershell
& 'C:\Users\Eric\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\manage_tokens.py list
```

Os hashes ficam salvos em [config/access_tokens.json](/C:/Users/Eric/Documents/GitHub/download_emendas/config/access_tokens.json).

## Como testar

1. Rode `launch.py`.
2. Abra `http://127.0.0.1:8501`.
3. Entre com um token valido.
4. Troque entre `Emendas` e `Documentos`.
5. Abra um filtro como `nome_autor`, digite parte do nome e marque algumas opcoes.
6. Escolha as colunas que deseja baixar.
7. Confirme que a tabela ficou com scroll proprio, sem expandir a pagina inteira.
8. Baixe em `CSV` ou `Excel`.

## Dependencias principais

- `duckdb`
- `jinja2`
- `openpyxl`
- `pandas`
- `pyarrow`
- `starlette`
- `uvicorn`
