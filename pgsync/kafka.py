"""Utils to interact with kafka."""

import logging
import sys
import time

import orjson
from confluent_kafka import Producer

from . import settings

logger = logging.getLogger(__name__)


class KafkaProducer:
    """Custom kafka producer."""

    def __init__(self, topic: str, **kwargs):
        """Performant kafka producer."""
        self.topic = f"pgysnc-{topic}"
        self.producer = Producer(
            {
                "bootstrap.servers": settings.KAFKA_BROKER_SERVERS,
                "message.send.max.retries": 3,  # this is the default
                "partitioner": "consistent_random",
                # some tuning based on confluent recs
                # "batch.size": 1_000_000,
                "linger.ms": 100,
                "acks": 1,
                "compression.type": "lz4",
                "queue.buffering.max.messages": 100_000,
                **kwargs,
            }
        )
        self.last_flushed_at = time.time()

        try:
            self.producer.list_topics(timeout=10)
        except Exception as e:
            logger.error(f"Failed to connect to Kafka broker servers: {e}")
            sys.exit(1)

    def _default_delivery_callback(self, err, msg):
        if err:
            message_id = msg.key()
            if isinstance(message_id, bytes):
                message_id = message_id.decode("utf-8")
            logger.info("Message %s failed delivery: %s", message_id, err)

    def possibly_flush(self, force=False):
        """Flush the producer if it's getting big or hasn't been flushed in a while."""
        if (
            force
            or len(self.producer) > settings.KAFKA_MAX_MSG_BEFORE_FLUSH
            or time.time() - self.last_flushed_at > settings.KAFKA_MAX_SEC_BEFORE_FLUSH
        ):
            self.producer.flush(2)
            self.last_flushed_at = time.time()

    def produce(self, data: dict, **kwargs):
        """Produce data to kafka."""
        try:
            self.producer.produce(
                self.topic,
                value=orjson.dumps(data, option=orjson.OPT_SERIALIZE_NUMPY),
                on_delivery=self._default_delivery_callback,
                **kwargs,
            )
            _ = self.producer.poll(0)
            self.possibly_flush()

        except BufferError as e:
            st = time.time()
            num_buffered_messages = len(self.producer)
            self.producer.poll(2)
            logger.exception(
                f"Failed to produce message to kafka: {e}; "
                f"flush of {num_buffered_messages} messages took {time.time() - st:0.2f} seconds"
            )
        except Exception as e:
            logger.exception(f"Failed to produce message to kafka: {e}")

    def produce_batch(self, data: list, **kwargs):
        """Produce a batch of data to kafka."""
        for d in data:
            self.produce(d, **kwargs)
