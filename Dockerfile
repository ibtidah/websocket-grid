FROM python:3.7-slim
RUN apt-get update
RUN apt-get install -y git python3-pip
COPY ./requirements.txt /app/requirements.txt
WORKDIR /app
RUN pip3 install -r requirements.txt
COPY . /app
WORKDIR /app
ENTRYPOINT ["python3"]
CMD ["websocket_app.py"]
