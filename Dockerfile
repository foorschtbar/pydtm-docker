FROM python:3

WORKDIR /usr/src/app

COPY ./assets ./

CMD [ "python", "./pydtm.py" ]