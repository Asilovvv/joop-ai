#!/usr/bin/env bash
# Joop AI on a fresh Ubuntu or Debian server: from an empty server to a running panel with one command.
#
#   curl -fsSL https://raw.githubusercontent.com/Asilovvv/joop-ai/main/deploy/setup.sh -o setup.sh
#   sudo bash setup.sh
#
# It asks for the domain and the Anthropic API key (and, if you want alerts, a Telegram bot token), then:
# installs Docker and git if missing, gets the code into /opt/joop-ai, writes .env with fresh secrets
# (session secret, token encryption key, founder console password), checks DNS, builds, migrates,
# makes one tiny model call to check the key and the balance, starts, and waits for HTTPS.
# Running it again keeps the existing .env and only updates the code and restarts.
#
# Answers can be given in advance (for automation and tests): JOOP_DOMAIN, JOOP_ANTHROPIC_KEY,
# JOOP_FOUNDER_BOT_TOKEN, JOOP_FOUNDER_CHAT_ID, JOOP_PRICE_SOM. JOOP_DIR (default /opt/joop-ai), JOOP_REPO.
# DRY_RUN=1 only writes .env in JOOP_DIR (no root, no Docker, no network): used by the tests.
set -euo pipefail

DIR=${JOOP_DIR:-/opt/joop-ai}
REPO=${JOOP_REPO:-https://github.com/Asilovvv/joop-ai.git}
DRY_RUN=${DRY_RUN:-0}

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\nОшибка: %s\n' "$*" >&2; exit 1; }
ask() {  # ask "Вопрос" VAR_NAME [default]: an answer given in the environment is used as is
    local prompt=$1 name=$2 default=${3:-} answer=${!2:-}
    if [ -z "$answer" ]; then
        [ -r /dev/tty ] || fail "нет терминала для вопроса «$prompt»: задайте $name заранее"
        read -r -p "$prompt" answer </dev/tty || true
    fi
    printf -v "$name" '%s' "${answer:-$default}"
}
random_hex() { openssl rand -hex 32; }
fernet_key() { openssl rand -base64 32 | tr '+/' '-_'; }  # the format of `python -m joop gen-key`
random_password() { openssl rand -base64 24 | tr -d '/+=' | cut -c1-20; }
set_env() {  # set_env KEY VALUE: replace the line KEY=... in .env (values are written as is)
    local key=$1 value=$2 tmp
    tmp=$(mktemp)
    grep -v "^${key}=" .env >"$tmp" || true
    printf '%s=%s\n' "$key" "$value" >>"$tmp"
    cat "$tmp" >.env
    rm -f "$tmp"
}

# --- 1. the server ---------------------------------------------------------------------------------------
if [ "$DRY_RUN" != 1 ]; then
    [ "$(id -u)" = 0 ] || fail "запустите от root: sudo bash setup.sh"
    command -v openssl >/dev/null || { apt-get update -qq && apt-get install -y -qq openssl; }
    command -v git >/dev/null || { say "Ставлю git"; apt-get update -qq && apt-get install -y -qq git; }
    command -v docker >/dev/null || { say "Ставлю Docker (2–3 минуты)"; curl -fsSL https://get.docker.com | sh; }
    if [ -d "$DIR/.git" ]; then
        say "Обновляю код в $DIR"
        git -C "$DIR" pull --ff-only
    else
        say "Скачиваю код в $DIR"
        git clone --depth 1 "$REPO" "$DIR"
    fi
fi
cd "$DIR"

# --- 2. settings -----------------------------------------------------------------------------------------
if [ -f .env ] && [ "${JOOP_NEW_ENV:-0}" != 1 ]; then
    say "Файл .env уже есть — оставляю его как есть (новый: JOOP_NEW_ENV=1)."
    OWNER_PASSWORD_NEW=""
else
    [ -f .env.example ] || fail "нет .env.example в $DIR"
    ask "Домен (например joop.kg, без https://): " JOOP_DOMAIN
    JOOP_DOMAIN=$(printf '%s' "$JOOP_DOMAIN" | sed -E 's#^https?://##; s#/.*$##' | tr '[:upper:]' '[:lower:]')
    printf '%s' "$JOOP_DOMAIN" | grep -Eq '^[a-z0-9.-]+\.[a-z]{2,}$' || fail "это не похоже на домен: $JOOP_DOMAIN"
    ask "Ключ Anthropic API (sk-ant-…): " JOOP_ANTHROPIC_KEY
    case "$JOOP_ANTHROPIC_KEY" in sk-ant-*) ;; *) fail "ключ Anthropic начинается с sk-ant-";; esac
    ask "Цена подписки в сомах в месяц (Enter — решите позже): " JOOP_PRICE_SOM ""
    printf '%s' "${JOOP_PRICE_SOM:-0}" | grep -Eq '^[0-9]+$' || fail "цена — целое число сомов"
    ask "Токен Telegram-бота для ваших оповещений о сбоях (Enter — без оповещений): " JOOP_FOUNDER_BOT_TOKEN ""

    cp .env.example .env
    chmod 600 .env
    OWNER_PASSWORD_NEW=$(random_password)
    set_env ANTHROPIC_API_KEY "$JOOP_ANTHROPIC_KEY"
    set_env SESSION_SECRET "$(random_hex)"
    set_env TOKEN_ENCRYPTION_KEY "$(fernet_key)"
    set_env DOMAIN "$JOOP_DOMAIN"
    set_env PUBLIC_BASE_URL "https://$JOOP_DOMAIN"
    set_env SECURE_COOKIES true
    set_env OWNER_PASSWORD "$OWNER_PASSWORD_NEW"
    [ -n "${JOOP_PRICE_SOM:-}" ] && set_env PRICE_SOM "$JOOP_PRICE_SOM"
    if [ -n "$JOOP_FOUNDER_BOT_TOKEN" ]; then
        set_env FOUNDER_BOT_TOKEN "$JOOP_FOUNDER_BOT_TOKEN"
        if [ -z "${JOOP_FOUNDER_CHAT_ID:-}" ] && [ "$DRY_RUN" != 1 ]; then
            ask "Напишите этому боту любое сообщение в Telegram и нажмите Enter: " _SENT " "
            JOOP_FOUNDER_CHAT_ID=$(curl -fsS "https://api.telegram.org/bot${JOOP_FOUNDER_BOT_TOKEN}/getUpdates" \
                | grep -oE '"chat":\{"id":-?[0-9]+' | tail -1 | grep -oE -- '-?[0-9]+$' || true)
            [ -n "$JOOP_FOUNDER_CHAT_ID" ] || say "Не нашёл сообщение боту: оповещения не включены (FOUNDER_CHAT_ID можно вписать в .env позже)."
        fi
        [ -n "${JOOP_FOUNDER_CHAT_ID:-}" ] && set_env FOUNDER_CHAT_ID "$JOOP_FOUNDER_CHAT_ID"
    fi
    say "Настройки записаны в $DIR/.env (доступ только у root)."
fi

if [ "$DRY_RUN" = 1 ]; then
    echo "DRY_RUN: .env записан, Docker не запускался."
    exit 0
fi

# --- 3. DNS ----------------------------------------------------------------------------------------------
DOMAIN=$(grep -E '^DOMAIN=' .env | tail -1 | cut -d= -f2-)
MY_IP=$(curl -fsS -4 https://api.ipify.org 2>/dev/null || true)
DNS_IP=$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk 'NR==1{print $1}' || true)
if [ -n "$MY_IP" ] && [ "$DNS_IP" != "$MY_IP" ]; then
    say "Внимание: домен $DOMAIN указывает на ${DNS_IP:-ничего}, а у сервера адрес $MY_IP."
    echo "В настройках DNS домена добавьте запись A: имя @, значение $MY_IP. Сертификат HTTPS выдадут, когда запись заработает"
    echo "(от минут до нескольких часов). Продолжаю: сервер дождётся DNS сам."
fi

# --- 4. build, check, start ------------------------------------------------------------------------------
say "Собираю (первый раз 3–5 минут)"
docker compose build
docker compose run --rm app python -m joop migrate
say "Проверяю настройки и ключ Anthropic (один короткий запрос к модели)"
if ! docker compose run --rm app python -m joop check --live; then
    fail "проверка не прошла: исправьте пункты «НУЖНО» в $DIR/.env (nano $DIR/.env) и запустите setup.sh снова"
fi
docker compose up -d
say "Жду HTTPS на https://$DOMAIN (до 3 минут)"
ok=0
for _ in $(seq 1 36); do
    if curl -fsS -m 5 "https://$DOMAIN/health" >/dev/null 2>&1; then ok=1; break; fi
    sleep 5
done

# --- 5. what next ----------------------------------------------------------------------------------------
say "Готово."
if [ "$ok" = 1 ]; then echo "Сайт работает: https://$DOMAIN"; else echo "Сервер запущен, но https://$DOMAIN пока не отвечает — скорее всего, ещё не обновился DNS. Проверьте позже: curl https://$DOMAIN/health"; fi
echo "Регистрация компаний:      https://$DOMAIN/signup"
echo "Консоль основателя:        https://$DOMAIN/owner"
[ -n "${OWNER_PASSWORD_NEW:-}" ] && echo "Пароль консоли основателя: $OWNER_PASSWORD_NEW  (запишите; он также в $DIR/.env)"
echo
echo "Сохраните копию $DIR/.env вне сервера: без TOKEN_ENCRYPTION_KEY из него сохранённые токены каналов не прочитать."
echo "Обновить потом: sudo bash $DIR/deploy/setup.sh   ·   Логи: cd $DIR && docker compose logs -f app"
