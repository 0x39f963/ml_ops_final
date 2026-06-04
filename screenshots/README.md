# Скриншоты: локальный запуск всех частей системы

Кадры сняты на localhost. В кадре только публичные имена: `client_id`-хэш, `PROD_xx`, `SEG_x` (без реальных ИНН и названия компании).

В скобках у каждого - критерий оценки, который кадр подтверждает (C1 цель, C2 зрелость Level 2, C3 создание/работа сервиса, C4 риски, C5 MDD).

---

## Сервис и продукт

### Контракт scoring-API (C1)
Эндпоинты сервиса: `/health`, `/score`, `/batch-score`, `/model-info`, `/metrics`.

![swagger](api_swagger.png)

### Demo: топ-10 по клиенту (C1)
Вводим клиента - получаем топ-10 продуктов с вероятностью. Режим `inn`: реальный ИНН хэшируется прямо в браузере, в API уходит только `client_id`-хэш.

![demo](demo_top10.png)

### `/health` -> 200 (C3)
Сервис жив, модель загружена по alias `champion`.

![health](api_health.png)

---

## Зрелость Level 2: переобучение и переключение модели

### Airflow DAG переобучения (C2)
Конвейер `nbo_retrain_pipeline`.

![airflow dags](airflow_dags.png)

### Прогон DAG со всеми задачами (C2)
Видны все задачи, включая ветку `compare_with_champion -> register_model / skip_deploy` (автоматический вывод плохой модели через переключение трафика).

![airflow run](airflow_dag_run.png)

---

## Инфраструктура

### docker ps - сервисы Up(healthy) (C3)
Весь стек поднят одной командой, у сервисов healthcheck.

![docker ps](docker_ps_healthy.png)

### docker stats - сервисы под нагрузкой (C3)
Потребление ресурсов: контейнеры NBO (в красной рамке) живые и работают.

![docker stats](docker_stats.png)

---

## Что еще снять (по мере готовности)

- MLflow, страница Models с alias `champion` / `challenger` (усилит C2);
- Grafana, дашборд `nbo_overview` (C4);
- Prometheus, targets где `nbo-api` UP (C4);
- публичный `/health` с облака (нужно для C3 на максимум).

Полный каталог evidence (включая текстовые логи) - в [INDEX.md](INDEX.md).
