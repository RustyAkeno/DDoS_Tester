# DDoS_Tester
нагрузочный тест на asyncio и aiohttp
# Поддерживает:
 HTTP и HTTPS,
 GET и POST,
 JSON и raw body,
 настройку concurrency,
 лимит RPS,
 сводку по скорости и ошибкам,
 отключение проверки SSL при необходимости.
 
# Установка
     pip install aiohttp

# Примеры запуска

# Высокая нагрузка GET по HTTPS

     python async_stress.py --url https://your-server.com/ --method GET --concurrency 1000 --duration 60


# POST с JSON

      python async_stress.py --url https://your-server.com/api --method POST --json --payload-size 2048 --concurrency 800 --duration 60


# POST с отключением проверки сертификата

       python async_stress.py --url https://your-server.com/api --method POST --text --insecure --concurrency 1000 --duration 60


# С лимитом в 5000 RPS

       python async_stress.py --url https://your-server.com/api --method POST --json --concurrency 2000 --rps 5000 --duration 60


# Важные советы для тысяч RPS

• увеличь ulimit -n

• запускай на машине с хорошей сетью

• для очень больших нагрузок подними concurrency

• если сервер локальный, сначала проверь localhost

• для HTTPS большое количество соединений может упереться в CPU на шифровании

• если нужна максимальная производительность, лучше тестировать с нескольких машин
