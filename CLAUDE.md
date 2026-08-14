# CLAUDE.md

このファイルは、このリポジトリで作業する Claude Code (claude.ai/code) へのガイダンスを提供します。

## プロジェクトの状態

YouTubeダウンロードタスクの進捗をRedis経由で監視し、状態変化(処理開始/完了/エラー)をDiscordチャンネルへ通知するDiscordボット(`app/main.py`)。Redis上の `youtube_download_statuses` ハッシュをポーリングし、前回値との差分があれば通知して、`done`/`error` になったタスクはRedisから削除する。ボット本体とは別に、タスクをRedisへ書き込む側(ダウンロード処理そのもの)は別リポジトリ(`ssmc-network/home-api`)/別プロセスの想定で、このリポジトリはあくまで通知ボット。

**重複通知防止の状態はRedis側(`youtube_download_notified_statuses` ハッシュ)に持たせている**(プロセスメモリではない)。以前はPythonプロセス内の辞書(`previous_status`)だけで「前回通知した状態」を覚えていたため、botの再起動やレプリカの重複起動を挟むとメモリがリセットされ、Redis上にまだ残っている`done`/`error`のタスクを「初めて見た」と誤認して同じ完了通知を何度も送ってしまうバグがあった(実際に同一タスクの完了通知が3連続で届いた事例で発覚)。`youtube_download_notified_statuses` へ`task_id → 最後に通知した状態`を書き込むようにし、この状態をRedis側の恒久データとして扱うことで、プロセスが何度再起動しても同じ状態変化を二重に通知しないようにしている。`done`/`error`の削除(`cleanup_task`)は通知済みかどうかに関わらず毎回試行する(`hdel`は対象が無くても冪等なため、前回の削除失敗時の再試行を兼ねる)。

## コマンド

依存関係はPoetryで管理し、`dev` ターゲットのDockerコンテナ内(Python 3.13)で実行する。ローカルvenvのワークフローは用意されていない — コンテナを使うこと。

- 開発コンテナ起動: `docker compose up -d`(`compose.yml` を使用、`dev` ターゲットをビルドし `/bin/bash` に入る)
- コンテナ内でコマンド実行: `docker compose exec app <command>`、例: `docker compose exec app ruff check .`
- Lint: `ruff check .`(コンテナ内、`/usr/src/app` から実行)
- フォーマット: `ruff format .`
- 型チェック: `mypy .`
- テスト: `pytest`(`tool.pytest.ini_options` で `testpaths = ["tests"]` を設定済みだが、`tests/` ディレクトリ自体はまだ無い — CI(`test.yaml`)も `[ -d tests ]` のガードで未整備を許容している)
- 依存関係インストール(コンテナ内): `poetry install`(開発用)または `poetry install --without dev`(本番用)
- 本番ビルド: `docker build --target prd .` / `docker compose -f compose.prd.yml up`

## ブランチ運用とCI/CD

**ブランチモデル**: `main`(保護ブランチ、直pushは不可) / `release/<バージョン>`(例: `release/1.0.0`) / 開発ブランチ(`feature/...`、`claude/...` など)の3層。

1. リリースするバージョンの `release/<バージョン>` ブランチを先に切る
2. 開発ブランチを `release/<バージョン>` から切って作業し、完了したらPRで `release/<バージョン>` にマージする(これを繰り返す)
3. `release/<バージョン>` が完成したらPRで `main` にマージする

**Claude CodeはPRのマージを実施しないこと。** PR(開発ブランチ→`release/<バージョン>`、`release/<バージョン>`→`main` のいずれも)の作成はしてよいが、実際のマージ操作はユーザー側が行う。CIの確認・レビュー・不具合修正はこれまで通り主体的に行ってよいが、マージ自体は必ずユーザーの実施に委ねること。

**CI(`.github/workflows/`)** — eq-dashboardリポジトリと同じ構成に合わせている:

- `test.yaml` — `release/*` へのPRで実行(`workflow_dispatch` でも手動実行可)。`dev` ターゲットのDockerイメージをビルドし、その中で `ruff check .` / `ruff format --check .` / (`tests/` があれば)`pytest` を実行する。続けて `prd` ターゲットもpushせずローカルビルドし、Docker Hub OIDCでログインした上で Docker Scout(`docker scout cves`)による脆弱性スキャンを行う。結果はcritical/high のみに絞った上でそのPRへ固定マーカー(`<!-- docker-scout-report -->`)付きコメントとして投稿し、再実行時は新規コメントを増やさず上書きする(medium/lowを含む全件は `docker-scout-report-pr-<PR番号>` という名前のArtifactとして90日保持)。この脆弱性スキャンは意図的に `main` マージ前(release/*へのPR時点)に置いている — マージ後(=Docker Hub公開後)に気づくのではなく、公開前に気づけるようにするため。`workflow_dispatch` での手動実行時は `context.issue.number` が無いためPRコメントはスキップし、結果はジョブの実行サマリー(`core.summary`)にのみ出力する。
- `build.yaml` — `main` への **push** で実行する(`main` は直pushできない保護ブランチだが、PRをマージボタンでマージするとGitHub自身が `main` へマージコミットをpushする形になるため `push` イベントは発火する)。バージョン番号はマージコミットのメッセージ(GitHubが自動生成する `Merge pull request #N from <owner>/release/<version>`、`github.event.head_commit.message`)から正規表現で抽出する(マージ戦略を「Create a merge commit」以外に変更した場合はこの抽出が壊れる点に注意)。`prd` ターゲットのイメージを `latest` とそのバージョンタグの両方でDocker Hubへpushする。脆弱性スキャンは `test.yaml` 側に一本化しており、ここでは行わない。

**Docker Hub認証(OIDC)**: 静的PAT(`secrets.DOCKER_TOKEN`)は使用しない。`docker/oidc-action@v1`(`with: connection-id: ${{ vars.DOCKERHUB_OIDC_CONNECTIONID }}`)でGitHub ActionsのOIDCトークンをDocker Hubで検証させ、短命アクセストークンを取得してから `docker/login-action` の `password` に渡す2段階構成(`username` はDocker Hub Organization名 `ssmcnetwork` 固定)。`DOCKERHUB_OIDC_CONNECTIONID` はリポジトリのActions **Variable**(Secretではない)。イメージ名は `${{ github.repository }}` に依存させず `ssmcnetwork/home-discord-bot` 固定にしている(GitHub Organization名 `ssmc-network` とDocker Hub Organization名 `ssmcnetwork` は、Docker Hub側がハイフンを許容しないため完全一致しない — Docker Hub側の制約であり是正不可能)。**`docker scout cves` はpush/pull先に関係なくローカルのみのイメージに対してもDocker Hubへのログインを要求する**ため、`test.yaml`(pushしない `prd` イメージのスキャン)にも `build.yaml` と同じOIDCログインステップが入っている。加えて、Dockerfileのベースイメージが `dhi.io`(Docker Hardened Images専用レジストリ、後述)から取得するため、両ワークフローとも `docker.io` へのログインに続けて `dhi.io` へも同じOIDCトークンでログインしている(DHIはDocker Hubアカウントの認証情報をそのまま使う仕様のため、同一トークンで通る — CI実行で動作確認済み)。

**Docker Hub側の設定(このリポジトリではまだ未作成 — Docker Hubの管理画面はこのセッションから操作できないため、ユーザー側での設定が必要)**:

- Docker Hub OIDC connectionを**このリポジトリ専用に1つ**作成する(他リポジトリと使い回さない — ルールセットが1 connectionあたり最大5本までのため、および用途ごとに権限を絞りやすくするため)。connection名はリポジトリ名に合わせて `home-discord-bot` を推奨。
- ルールを2本設定する: `main` ブランチへのpush用(scope: `Image Push`)、`release/*` 向けPR(Docker Scout用、scope: `Image Pull`のみ)。
- **Subject claimは名前ベースではなくID埋め込み形式で登録すること(重要・ハマりどころ)**: 素直に `repo:ssmc-network/home-discord-bot:ref:refs/heads/main` のような名前ベースで登録すると、実際にGitHub Actionsが発行するOIDCトークンとマッチせずログインに失敗する。[2026年7月15日のGitHubの仕様変更](https://github.blog/changelog/2026-04-23-immutable-subject-claims-for-github-actions-oidc-tokens/)以降、新規作成・リネーム・Transferされたリポジトリではsub claimがOrganization ID・Repository IDを埋め込んだ「immutable形式」になる。このリポジトリのOrganization ID(`ssmc-network`)は `174979090`、Repository ID(`home-discord-bot`)は `1001598293` なので、2本のルールは次の値で登録する(eq-dashboardの前例に倣い、`pull_request` イベント用はワイルドカードにしている):
  - `main` へのpush用(scope: `Image Push`): `repo:ssmc-network@174979090/home-discord-bot@1001598293:ref:refs/heads/main`
  - `release/*` 向けPR用(scope: `Image Pull`): `repo:ssmc-network@174979090/home-discord-bot@1001598293:*`
- `DOCKERHUB_OIDC_CONNECTIONID` をリポジトリのActions Variables(Settings → Secrets and variables → Actions → Variables)に登録する。
- Docker Hub上に `ssmcnetwork/home-discord-bot` リポジトリが無ければ作成しておく。
- Docker Hardened Images (DHI) はTeamライセンスの無料枠を利用する前提(エンタープライズ限定のミラーレジストリ機能は使わない)。ベースイメージは `dhi.io/python:3-debian-dev`(ビルド/開発用、pip・poetryが使える)と `dhi.io/python:3`(本番ランタイム用、最小構成)の2種類を使い分けている。

**DHIイメージの更新検知(digest固定 + Renovate)**: `dhi.io/python:3-debian-dev`・`dhi.io/python:3` はいずれも浮動タグ(タグ名は変わらないまま中身だけDocker側で更新される)なので、Dockerfileの `ARG PYTHON_DEV_IMAGE`/`PYTHON_PRD_IMAGE` は `@sha256:...` でdigest固定している。固定するだけだと更新に気づけないため、`renovate.json`(`enabledManagers: ["dockerfile"]` のみ有効化、他のマネージャー(poetry/GitHub Actionsなど)は今回のスコープ外として明示的に無効化している)でRenovateにDockerfileを監視させ、DHI側で新しいビルドが出るたびに「digestを更新するPR」が自動生成されるようにしている。このPRは `release/*` 向けなので `test.yaml` が自動でDocker Scoutの再スキャンも走らせ、そのPR上で脆弱性が直ったかどうかも一緒に確認できる。dhi.ioのdigest確認にはRenovate側にもDocker Hubの静的な資格情報が必要(OIDCはRenovateからは使えないため)で、`renovate.json` の `hostRules` は `{{ secrets.DHI_IO_DOCKERHUB_PAT }}` というRenovateのシークレット参照になっている。**運用にはユーザー側で以下の設定が必要**(このセッションからは操作不可):
  - Mend Renovate GitHub Appをこのリポジトリにインストールする(GitHub Marketplaceから)。
  - MendのダッシュボードでこのリポジトリにRepository Secret `DHI_IO_DOCKERHUB_PAT`(Docker Hubの読み取り専用PAT)を登録する。
  - 現在Dockerfileに埋め込まれているdigestは、`docker buildx imagetools inspect <image>` をCI経由(dhi.ioへログイン済みの環境)で実行して取得したもの。手元で最新化する場合も同じコマンドで確認できる。

## アーキテクチャ

- **マルチステージDockerfile**: `base`(`dhi.io/python:3-debian-dev`) → `dependencies` → `dev-dependencies` → `dev` / `prd`。OpenShift向けのUBIベースイメージではなく、通常のKubernetes環境向けにDocker Hardened Images (DHI) を使用している。ビルド系のステージ(`base`/`dependencies`/`dev-dependencies`/`dev`)は開発ツール入りの `-debian-dev` バリアントを使うが、`prd` だけは `base` を継承せず最小構成の `dhi.io/python:3` から独立して作っている(実行時イメージに開発ツールを含めないため)。
- **Poetryの依存関係はプロジェクト内 `.venv` に分離**(`POETRY_VIRTUALENVS_CREATE=true` + `POETRY_VIRTUALENVS_IN_PROJECT=true`)。`dependencies` ステージで `poetry config virtualenvs.options.no-pip true` を設定し、`.venv` に `pip` 自体を含めない(本番イメージにpip由来の脆弱性が紛れ込むのを防ぐため)。`dev`/`prd` はいずれも `dependencies`/`dev-dependencies` ステージから `.venv` の中身だけを `COPY --from` で引き継ぎ、poetry自身やビルド専用の依存(setuptoolsなど)は最終イメージに含めない。`dev` は `dev-dependencies`(devグループ込み)から、`prd` は `dependencies`(本番依存のみ)から `.venv` をコピーする。
- **Poetryのpackage-modeは無効化**(`app/pyproject.toml` の `package-mode = false`)— 配布可能なパッケージではなく、単なるアプリケーションとして扱っている。
- **Ruff/mypy/pytestの設定**: `app/pyproject.toml`。Ruffは `select = ["ALL"]` + 広範な `ignore` リストではなく、`select = ["B", "E", "F", "I", "N", "W", "C90", "PL", "RUF", "UP"]` という絞り込んだルールセットを採用している(line-length 119、target-version は実際のPython制約(`^3.13`)に合わせて `py313`)。mypyは `disallow_untyped_defs` / `warn_return_any` などを有効にした比較的厳格な設定。pytestは `testpaths = ["tests"]` / `pythonpath = ["."]`。
- **JSON形式のアプリケーションログ**(`app/core/log_modules.py` の `log_application(name)`): `TimeStampFormatter` が `settings.tz`(既定 `Asia/Tokyo`、compose の `TZ` 環境変数と揃える)を使ってタイムスタンプをローカル時刻のISO8601で出力し、`LogApplicationJSONFormatter` が `timestamp`/`level`/`message`/`service`/`tag`/`details`(`function`/`argument`/`error_message`/`stacktrace`)のJSONを1行で出力する。`main.py`/`modules/redis_module.py` は素の `logging.basicConfig` ではなくこの `log_application(__name__)` を使うこと。このボットはFastAPI/uvicornのようなASGIサーバーを持たない(discord.pyの `client.run()` で動くだけ)ため、uvicorn用のログ設定(`log_config.yaml`、アクセスログ用の `HealthCheckFilter` 等)は導入していない — Webサーバーを追加する場合はそのタイミングで検討すること。`zoneinfo` がタイムゾーンデータを解決できるよう、`tzdata` を明示的に依存関係へ追加している(コンテナのベースイメージにOS側のtzdataが無い場合のフォールバック)。
- 両方のcomposeファイルで `TZ=Asia/Tokyo` を指定している — スケジューリングや時刻を扱う機能を追加する際もこれを維持すること。
