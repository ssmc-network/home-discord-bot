# ==========================================
# グローバル設定
# ==========================================
# dhi.io は Docker Hardened Images 専用レジストリ。pull には
# `docker login dhi.io`(Docker Hubの認証情報)が必要。
# タグは浮動(latestの中身が無断で変わる)ため、digestで固定しRenovateに
# 更新PRを出させている(更新検知の仕組みはCLAUDE.md参照)。
ARG PYTHON_DEV_IMAGE=dhi.io/python:3-debian-dev@sha256:02173cae8b920c98ff9fab81eb1aefcadd229f158110553c6ed758dc935589dd
ARG PYTHON_PRD_IMAGE=dhi.io/python:3@sha256:0536ccad57c9be08128bd2a6f0982570086ec943a88033f4f53f7adffe407903
ARG POETRY_VERSION=2.4.1


# ==========================================
# ベースイメージ(依存関係のビルド用 = devバリアント)
# ==========================================
FROM ${PYTHON_DEV_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_INSTALLER_MAX_WORKERS=10 \
    POETRY_VIRTUALENVS_CREATE=true \
    POETRY_VIRTUALENVS_IN_PROJECT=true
WORKDIR /usr/src/app


# ==========================================
# 依存関係のビルド(本番用: 通常依存のみ)
# ==========================================
# poetry自体はここ(dependencies/dev-dependencies)にだけ入る。dev/prdへ
# 引き継ぐのは`poetry install`が作る.venv(プロジェクト内仮想環境)のみ
# (下のdev/prdステージのCOPY --fromを参照)。poetry自身やそのビルド時限りの
# 依存が本番イメージに紛れ込むのを防ぐための構成。
FROM base AS dependencies
ARG POETRY_VERSION

RUN pip install --upgrade --no-cache-dir pip && \
    pip install --no-cache-dir poetry=="${POETRY_VERSION}" && \
    poetry config virtualenvs.options.no-pip true

COPY ./app/pyproject.toml ./app/poetry.lock /usr/src/app/
RUN poetry install --without dev --no-root && \
    poetry cache clear pypi --all


# ==========================================
# 依存関係のビルド(devグループを含む完全版)
# ==========================================
FROM dependencies AS dev-dependencies

RUN poetry install --no-root && \
    poetry cache clear pypi --all


# ==========================================
# 開発用イメージ (dev)
# ==========================================
FROM base AS dev
ENV VIRTUAL_ENV=/usr/src/app/.venv \
    PATH=/usr/src/app/.venv/bin:$PATH

COPY --from=dev-dependencies /usr/src/app/.venv /usr/src/app/.venv
COPY ./ /usr/src/


# ==========================================
# 本番用イメージ (prd)
# ==========================================
# devバリアントではなく、最小構成のprdバリアントから作る。
FROM ${PYTHON_PRD_IMAGE} AS prd
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/usr/src/app/.venv \
    PATH=/usr/src/app/.venv/bin:$PATH
WORKDIR /usr/src/app

COPY --from=dependencies /usr/src/app/.venv /usr/src/app/.venv
COPY ./app /usr/src/app

CMD ["python", "main.py"]
