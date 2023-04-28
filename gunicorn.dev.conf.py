import os
import signal

from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter

# from opentelemetry.instrumentation.django import DjangoInstrumentor
# from opentelemetry.sdk.resources import SERVICE_NAME, Resource
# from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter


def worker_int(worker):
    os.kill(worker.pid, signal.SIGINT)


def post_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)", worker.pid)
    from opentelemetry.instrumentation.auto_instrumentation import sitecustomize  # noqa

    # resource = Resource.create(attributes={"service.name": "rosak-backend"})
    # trace.set_tracer_provider(TracerProvider(resource=resource))
    # span_processor = BatchSpanProcessor(OTLPSpanExporter(endpoint="http://jaeger:4317"))
    # trace.get_tracer_provider().add_span_processor(span_processor)
    # This call is what makes the Django application be instrumented
    # Refer: https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/django/django.html
    # DjangoInstrumentor().instrument(
    #     is_sql_commentor_enabled=True,
    # )
    # trace.set_tracer_provider(TracerProvider())
    # tracer = trace.get_tracer_provider().get_tracer(__name__)

    trace.get_tracer_provider().add_span_processor(
        BatchSpanProcessor(ConsoleSpanExporter())
    )

    # trace.set_tracer_provider(
    #     TracerProvider(
    #         resource=Resource.create(
    #             {
    #                 SERVICE_NAME: "rosak-backend",
    #             }
    #         )
    #     )
    # )
    # tracer = trace.get_tracer(__name__)

    span_processor = BatchSpanProcessor(
        JaegerExporter(
            agent_host_name="localhost",
            agent_port=6831,
            collector_endpoint="http://jaeger:14268/api/traces?format=jaeger.thrift",
        )
    )
    trace.get_tracer_provider().add_span_processor(span_processor)


# with tracer.start_as_current_span("foo"):
#     print("Hello world!")
