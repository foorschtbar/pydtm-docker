FROM python:3

WORKDIR /usr/src/app

COPY ./assets ./
#RUN pip install --no-cache-dir -r requirements.txt

#RUN chmod +x ./pydtm.py
CMD [ "python", "./pydtm.py" ]