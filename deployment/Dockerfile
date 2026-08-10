FROM public.ecr.aws/lambda/python:3.12

COPY pyproject.toml LICENSE ${LAMBDA_TASK_ROOT}/
COPY src ${LAMBDA_TASK_ROOT}/src
RUN pip install --no-cache-dir ".[cloud]"

CMD ["continuity_ledger.lambda_handler.lambda_handler"]
