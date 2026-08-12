# CLAUDE.md

このファイルは、このリポジトリで作業する Claude Code (claude.ai/code) へのガイダンスを提供します。

## プロジェクトの状態

現状はDiscordボット化を予定した再利用可能なPythonコンテナ基盤(`python-container-baseproject`)で、`app/` には依存関係・ツール設定(`pyproject.toml`、`poetry.lock`、`.vscode/`)のみがあり、アプリケーションのソースコードはまだない。ボットのコードは `app/` 配下に追加していく。

## コマンド

依存関係はPoetryで管理し、`develop` ターゲットのDockerコンテナ内(Python 3.13)で実行する。ローカルvenvのワークフローは用意されていない — コンテナを使うこと。

- 開発コンテナ起動: `docker compose up -d`(`compose.yml` を使用、`develop` ターゲットをビルドし `/bin/bash` に入る)
- コンテナ内でコマンド実行: `docker compose exec app <command>`、例: `docker compose exec app ruff check`
- Lint: `ruff check`(コンテナ内、`/usr/src/app` から実行)
- フォーマット: `ruff format`
- 型チェック: `mypy`(依存関係には存在するが、コマンド/CIともまだ組み込まれていない)
- 依存関係インストール(コンテナ内): `poetry install`(開発用)または `poetry install --without dev`(本番用)
- 本番ビルド: `docker build --target production .` / `docker compose -f compose.prd.yml up`

テスト・テストフレームワークは未整備。

## ブランチ運用とCI/CD

**ブランチモデル**: `main`(保護ブランチ、直pushは不可) / `release/<バージョン>`(例: `release/1.0.0`) / 開発ブランチ(`feature/...`、`claude/...` など)の3層。

1. リリースするバージョンの `release/<バージョン>` ブランチを先に切る
2. 開発ブランチを `release/<バージョン>` から切って作業し、完了したらPRで `release/<バージョン>` にマージする(これを繰り返す)
3. `release/<バージョン>` が完成したらPRで `main` にマージする

**Claude CodeはPRのマージを実施しないこと。** PR(開発ブランチ→`release/<バージョン>`、`release/<バージョン>`→`main` のいずれも)の作成はしてよいが、実際のマージ操作はユーザー側が行う。CIの確認・レビュー・不具合修正はこれまで通り主体的に行ってよいが、マージ自体は必ずユーザーの実施に委ねること。

**CI(`.github/workflows/`)** — eq-dashboardリポジトリと同じ構成に合わせている:

- `test.yaml` — `release/*` へのPRで実行(`workflow_dispatch` でも手動実行可)。`develop` ターゲットのDockerイメージをビルドし、その中で `ruff check .` / `ruff format --check .` / (`tests/` があれば)`pytest` を実行する。続けて `production` ターゲットもpushせずローカルビルドし、Docker Hub OIDCでログインした上で Docker Scout(`docker scout cves`)による脆弱性スキャンを行う。結果はcritical/high のみに絞った上でそのPRへ固定マーカー(`<!-- docker-scout-report -->`)付きコメントとして投稿し、再実行時は新規コメントを増やさず上書きする(medium/lowを含む全件は `docker-scout-report-pr-<PR番号>` という名前のArtifactとして90日保持)。この脆弱性スキャンは意図的に `main` マージ前(release/*へのPR時点)に置いている — マージ後(=Docker Hub公開後)に気づくのではなく、公開前に気づけるようにするため。`workflow_dispatch` での手動実行時は `context.issue.number` が無いためPRコメントはスキップし、結果はジョブの実行サマリー(`core.summary`)にのみ出力する。
- `build.yaml` — `main` への **push** で実行する(`main` は直pushできない保護ブランチだが、PRをマージボタンでマージするとGitHub自身が `main` へマージコミットをpushする形になるため `push` イベントは発火する)。バージョン番号はマージコミットのメッセージ(GitHubが自動生成する `Merge pull request #N from <owner>/release/<version>`、`github.event.head_commit.message`)から正規表現で抽出する(マージ戦略を「Create a merge commit」以外に変更した場合はこの抽出が壊れる点に注意)。`production` ターゲットのイメージを `latest` とそのバージョンタグの両方でDocker Hubへpushする。脆弱性スキャンは `test.yaml` 側に一本化しており、ここでは行わない。

**Docker Hub認証(OIDC)**: 静的PAT(`secrets.DOCKER_TOKEN`)は使用しない。`docker/oidc-action@v1`(`with: connection-id: ${{ vars.DOCKERHUB_OIDC_CONNECTIONID }}`)でGitHub ActionsのOIDCトークンをDocker Hubで検証させ、短命アクセストークンを取得してから `docker/login-action` の `password` に渡す2段階構成(`username` はDocker Hub Organization名 `ssmcnetwork` 固定)。`DOCKERHUB_OIDC_CONNECTIONID` はリポジトリのActions **Variable**(Secretではない)。イメージ名は `${{ github.repository }}` に依存させず `ssmcnetwork/home-discord-bot` 固定にしている(GitHub Organization名 `ssmc-network` とDocker Hub Organization名 `ssmcnetwork` は、Docker Hub側がハイフンを許容しないため完全一致しない — Docker Hub側の制約であり是正不可能)。**`docker scout cves` はpush/pull先に関係なくローカルのみのイメージに対してもDocker Hubへのログインを要求する**ため、`test.yaml`(pushしない `production` イメージのスキャン)にも `build.yaml` と同じOIDCログインステップが入っている。

**Docker Hub側の設定(このリポジトリではまだ未作成 — Docker Hubの管理画面はこのセッションから操作できないため、ユーザー側での設定が必要)**:

- Docker Hub OIDC connectionを**このリポジトリ専用に1つ**作成する(他リポジトリと使い回さない — ルールセットが1 connectionあたり最大5本までのため、および用途ごとに権限を絞りやすくするため)。connection名はリポジトリ名に合わせて `home-discord-bot` を推奨。
- ルールを2本設定する: `main` ブランチへのpush用(scope: `Image Push`)、`release/*` 向けPR(Docker Scout用、scope: `Image Pull`のみ)。
- **Subject claimは名前ベースではなくID埋め込み形式で登録すること(重要・ハマりどころ)**: 素直に `repo:ssmc-network/home-discord-bot:ref:refs/heads/main` のような名前ベースで登録すると、実際にGitHub Actionsが発行するOIDCトークンとマッチせずログインに失敗する。[2026年7月15日のGitHubの仕様変更](https://github.blog/changelog/2026-04-23-immutable-subject-claims-for-github-actions-oidc-tokens/)以降、新規作成・リネーム・Transferされたリポジトリではsub claimがOrganization ID・Repository IDを埋め込んだ「immutable形式」になる。このリポジトリのOrganization ID(`ssmc-network`)は `174979090`、Repository ID(`home-discord-bot`)は `1001598293` なので、`main` へのpush用ルールは `repo:ssmc-network@174979090/home-discord-bot@1001598293:ref:refs/heads/main` で登録する。`release/*` 向けPRルールのsub claim形式(`pull_request` イベント用)は実際にワークフローを実行した際のDocker Hub OIDC connectionのFailuresタブで実測して確認すること(eq-dashboardの前例に倣った)。
- `DOCKERHUB_OIDC_CONNECTIONID` をリポジトリのActions Variables(Settings → Secrets and variables → Actions → Variables)に登録する。
- Docker Hub上に `ssmcnetwork/home-discord-bot` リポジトリが無ければ作成しておく。

## アーキテクチャ

- **マルチステージDockerfile**: `base` → `prod-deps`/`develop` → `production`。Poetry自体はpip経由ではなく事前ビルド済みイメージ(`goegoe0212/poetry-image:latest`)から取得し、`virtualenvs.create false` によりシステムのPython環境へ直接依存関係をインストールする。`develop` は追加で `git` をインストールし、リポジトリ全体(`./`)をコピーする。`production` は `prod-deps` でインストール済みのパッケージの上に `app/` のみをコピーし、開発用依存関係を本番イメージから除外している。
- **Poetryのpackage-modeは無効化**(`app/pyproject.toml` の `package-mode = false`)— 配布可能なパッケージではなく、単なるアプリケーションとして扱っている。
- **Ruffのlint設定**: `app/pyproject.toml` で `select = ["ALL"]` を指定し、明示的な `ignore` リストで個別に除外している(line-length 120)。除外リストにないルールに引っかかるコードを書いた場合は、そのルールが明らかにこのプロジェクトに合わない場合を除き、ignoreを増やすのではなくコード側を直すこと。
- 両方のcomposeファイルで `TZ=Asia/Tokyo` を指定している — スケジューリングや時刻を扱う機能を追加する際もこれを維持すること。
