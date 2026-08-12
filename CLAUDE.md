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

**CI(`.github/workflows/`)**:

- `test.yaml` — `release/*` へのPRで実行。`develop` ターゲットのDockerイメージをビルドし、その中で `ruff check` と `ruff format` を実行する。
- `build.yaml` — `release/*` ブランチへの **push** で実行。`production` ターゲットをビルドし、Docker Hubへ `${{ github.repository }}:<release-version>`(バージョン = ブランチ名の `release/` 以降)としてpushし、Trivyでイメージをスキャンする。

現状このリポジトリでは `release/*` ブランチへのpushで直接ビルド・Docker Hubへのpushまで行っており、`main` へのマージ後に別途ビルド/デプロイするステップは無い。将来`main`マージ後のビルド/デプロイを追加する場合は、上記のブランチモデル(手順3の `release/<バージョン>` → `main` のPRマージ)を起点に設計すること。

## アーキテクチャ

- **マルチステージDockerfile**: `base` → `prod-deps`/`develop` → `production`。Poetry自体はpip経由ではなく事前ビルド済みイメージ(`goegoe0212/poetry-image:latest`)から取得し、`virtualenvs.create false` によりシステムのPython環境へ直接依存関係をインストールする。`develop` は追加で `git` をインストールし、リポジトリ全体(`./`)をコピーする。`production` は `prod-deps` でインストール済みのパッケージの上に `app/` のみをコピーし、開発用依存関係を本番イメージから除外している。
- **Poetryのpackage-modeは無効化**(`app/pyproject.toml` の `package-mode = false`)— 配布可能なパッケージではなく、単なるアプリケーションとして扱っている。
- **Ruffのlint設定**: `app/pyproject.toml` で `select = ["ALL"]` を指定し、明示的な `ignore` リストで個別に除外している(line-length 120)。除外リストにないルールに引っかかるコードを書いた場合は、そのルールが明らかにこのプロジェクトに合わない場合を除き、ignoreを増やすのではなくコード側を直すこと。
- 両方のcomposeファイルで `TZ=Asia/Tokyo` を指定している — スケジューリングや時刻を扱う機能を追加する際もこれを維持すること。
