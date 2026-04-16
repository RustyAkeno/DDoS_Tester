import argparse
import asyncio
import ssl
import time
import random
import string
from statistics import mean

import aiohttp

def make_payload(size: int) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=size))

async def fetch(session, method, url, payload, headers, timeout, insecure):
    start = time.perf_counter()
    try:
        ssl_ctx = False if insecure else None

        if method == "GET":
            async with session.get(url, timeout=timeout, ssl=ssl_ctx) as resp:
                await resp.read()
                status = resp.status
        else:
            async with session.post(
                url,
                data=payload,
                headers=headers,
                timeout=timeout,
                ssl=ssl_ctx,
            ) as resp:
                await resp.read()
                status = resp.status

        elapsed = time.perf_counter() - start
        return True, status, elapsed

    except Exception:
        elapsed = time.perf_counter() - start
        return False, None, elapsed

async def worker(name, session, args, stats, stop_event, rate_lock, rate_state):
    headers = {}

    if args.json:
        headers["Content-Type"] = "application/json"
    elif args.text:
        headers["Content-Type"] = "text/plain"

    payload = None
    if args.method == "POST":
        if args.json:
            payload = '{"data":"' + make_payload(args.payload_size) + '"}'
        elif args.text:
            payload = make_payload(args.payload_size)
        else:
            payload = ""

    while not stop_event.is_set():
        if args.rps > 0:
            async with rate_lock:
                now = time.perf_counter()
                if rate_state["window start"] is None:
                    rate_state["window start"] = now
                    rate_state["count"] = 0

                elapsed = now - rate_state["window start"]
                if elapsed >= 1.0:
                    rate_state["window start"] = now
                    rate_state["count"] = 0

                if rate_state["count"] >= args.rps:
                    sleep_for = 1.0 - elapsed if elapsed < 1.0 else 0.0
                    if sleep_for > 0:
                        await asyncio.sleep(sleep_for)
                    rate_state["window start"] = time.perf_counter()
                    rate_state["count"] = 0

                rate_state["count"] += 1

        ok, status, elapsed = await fetch(
            session=session,
            method=args.method,
            url=args.url,
            payload=payload,
            headers=headers,
            timeout=args.timeout,
            insecure=args.insecure,
        )

        async with stats["lock"]:
            stats["sent"] += 1
            stats["latencies"].append(elapsed)
            if ok and status is not None and 200 <= status < 400:
                stats["ok"] += 1
            else:
                stats["fail"] += 1

async def reporter(stats, stop_event, interval):
    last_sent = 0
    last_ok = 0
    last_fail = 0
    last_time = time.perf_counter()

    while not stop_event.is_set():
        await asyncio.sleep(interval)

        now = time.perf_counter()
        async with stats["lock"]:
            sent = stats["sent"]
            ok = stats["ok"]
            fail = stats["fail"]
            latencies = stats["latencies"][:]

        delta_sent = sent - last_sent
        delta_ok = ok - last_ok
        delta_fail = fail - last_fail
        elapsed = now - last_time
        rps = delta_sent / elapsed if elapsed > 0 else 0.0
        avg_lat = mean(latencies) if latencies else 0.0

        print(
            f"sent={sent} ok={ok} fail={fail} "
            f"rps={rps:.1f} interval_ok={delta_ok} interval_fail={delta_fail} "
            f"avg_latency={avg_lat:.4f}s"
        )

        last_sent = sent
        last_ok = ok
        last_fail = fail
        last_time = now

async def main_async():
    parser = argparse.ArgumentParser(description="Async HTTP/HTTPS load tester")
    parser.add_argument("--url", required=True, help="URL, например https://example.com/api")
    parser.add_argument("--method", choices=["GET", "POST"], default="GET")
    parser.add_argument("--concurrency", type=int, default=500, help="Количество одновременных задач")
    parser.add_argument("--duration", type=int, default=30, help="Длительность теста в секундах")
    parser.add_argument("--timeout", type=float, default=5.0, help="Таймаут запроса")
    parser.add_argument("--interval", type=int, default=2, help="Интервал отчёта в секундах")
    parser.add_argument("--payload-size", type=int, default=1024, help="Размер тела POST")
    parser.add_argument("--json", action="store_true", help="POST JSON")
    parser.add_argument("--text", action="store_true", help="POST plain text")
    parser.add_argument("--insecure", action="store_true", help="Не проверять SSL сертификат")
    parser.add_argument("--rps", type=int, default=0, help="Лимит запросов в секунду, 0 = без лимита")
    parser.add_argument("--keepalive", type=int, default=1000, help="Лимит keep-alive соединений")
    args = parser.parse_args()

    if args.method == "POST" and not args.json and not args.text:
        args.json = True

    timeout = aiohttp.ClientTimeout(total=args.timeout)
    connector = aiohttp.TCPConnector(
        limit=args.keepalive,
        limit_per_host=args.concurrency,
        ttl_dns_cache=300,
        ssl=False if args.insecure else None,
        enable_cleanup_closed=True,
    )

    stats = {
        "sent": 0,
        "ok": 0,
        "fail": 0,
        "latencies": [],
        "lock": asyncio.Lock(),
    }

    stop_event = asyncio.Event()
    rate_lock = asyncio.Lock()
    rate_state = {"window_start": None, "count": 0}

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        report_task = asyncio.create_task(reporter(stats, stop_event, args.interval))

        tasks = [
            asyncio.create_task(worker(f"w{i}", session, args, stats, stop_event, rate_lock, rate_state))
            for i in range(args.concurrency)
        ]

        start = time.perf_counter()
        try:
            while time.perf_counter() - start < args.duration:
                await asyncio.sleep(0.2)
        except KeyboardInterrupt:
            pass
        finally:
            stop_event.set()
            for task in tasks:
                task.cancel()

            await asyncio.gather(*tasks, return_exceptions=True)
            report_task.cancel()
            await asyncio.gather(report_task, return_exceptions=True)

    async with stats["lock"]:
        sent = stats["sent"]
        ok = stats["ok"]
        fail = stats["fail"]
        latencies = stats["latencies"][:]

    total_time = time.perf_counter() - start
    avg_lat = mean(latencies) if latencies else 0.0
    achieved_rps = sent / total_time if total_time > 0 else 0.0

    print("\nГотово")
    print(f"Время теста: {total_time:.2f} сек")
    print(f"Всего запросов: {sent}")
    print(f"Успешных: {ok}")
    print(f"Ошибок: {fail}")
    print(f"Средняя задержка: {avg_lat:.4f} сек")
    print(f"Средний RPS: {achieved_rps:.1f}")

if __name__ == "__main__":
    asyncio.run(main_async())
