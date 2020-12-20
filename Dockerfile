FROM python:3

WORKDIR /usr/src/app

COPY ./assets ./
RUN pip install --no-cache-dir -r requirements.txt

CMD [ "python", "./pydtm.py" ]