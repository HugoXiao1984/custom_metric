import asyncio
import aiohttp
import logging
from prometheus_client import Gauge, start_http_server
from aiohttp import ClientTimeout

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

custom_metric = Gauge('custom_metric', 'Custom metric for scaling')

PROMETHEUS_URL_ONPREM = "http://afd8678d7bc6f45049a3cc99365fff35-40c6394f178c1c92.elb.us-east-1.amazonaws.com:9090"
PROMETHEUS_URL_CLOUD = "http://kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090"

async def get_metric_value(url, query, retries=3):
    logger.debug(f"Querying {url} with query: {query}")
    timeout = ClientTimeout(total=10)  # 10 seconds timeout
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{url}/api/v1/query", params={'query': query}) as response:
                    if response.status == 200:
                        result = await response.json()
                        if result['data']['result']:
                            value = float(result['data']['result'][0]['value'][1])
                            logger.debug(f"Query result: {value}")
                            return value
                    logger.warning(f"Failed to get metric from {url}. Status: {response.status}")
        except asyncio.TimeoutError:
            logger.warning(f"Timeout when querying {url}. Attempt {attempt + 1} of {retries}")
        except Exception as e:
            logger.error(f"Error querying {url}: {e}")
        if attempt < retries - 1:
            await asyncio.sleep(1)  # Wait 1 second before retrying
    logger.error(f"Failed to get metric from {url} after {retries} attempts")
    return None

async def calculate_custom_metric():
    waiting_requests_onprem = await get_metric_value(PROMETHEUS_URL_ONPREM, 'num_requests_waiting{job="nim-llm-llama3-8b-instruct"}')
    running_requests_cloud = await get_metric_value(PROMETHEUS_URL_CLOUD, 'avg(avg_over_time(num_requests_running{job="nim-llm-llama3-8b-instruct"}[2m]))')
    waiting_requests_cloud = await get_metric_value(PROMETHEUS_URL_CLOUD, 'avg(avg_over_time(num_requests_waiting{job="nim-llm-llama3-8b-instruct"}[2m]))')

    logger.info(f"Waiting requests (onprem): {waiting_requests_onprem}, Running requests (cloud): {running_requests_cloud}, Waiting requests (cloud): {waiting_requests_cloud}")

    if waiting_requests_onprem is None and running_requests_cloud is None and waiting_requests_cloud is None:
        logger.error("All Prometheus instances failed to respond")
        return 0.5  # Default value when all fail

    if waiting_requests_onprem is None:
        waiting_requests_onprem = 0
        logger.warning("Using 0 for waiting_requests_onprem due to query failure")

    if running_requests_cloud is None:
        running_requests_cloud = 0
        logger.warning("Using 0 for running_requests_cloud due to query failure")

    if waiting_requests_cloud is None:
        waiting_requests_cloud = 0
        logger.warning("Using 0 for waiting_requests_cloud due to query failure")

    if waiting_requests_onprem > 20:
        return 1
    elif running_requests_cloud > 10:
        return 1
    elif running_requests_cloud < 5:
        return 0
    else:
        return 0.5

async def main():
    logger.info("Starting the custom metric server")
    start_http_server(8000)
    logger.info("HTTP server started on port 8000")

    while True:
        try:
            metric_value = await calculate_custom_metric()
            custom_metric.set(metric_value)
            logger.info(f"Custom metric value set to: {metric_value}")
        except Exception as e:
            logger.error(f"Error occurred: {e}", exc_info=True)

        logger.debug("Waiting for 30 seconds before next update")
        await asyncio.sleep(30)

if __name__ == "__main__":
    logger.info("Starting the application")
    asyncio.run(main())
