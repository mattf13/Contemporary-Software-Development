import sqlite3
import uuid
from flask import request
from flask import Flask
from flask import Response
import threading
import json
import time
import logging
from datetime import datetime
import pika
import os
import consul


app = Flask(__name__)


@app.route("/")
def hello():
    return "Hello from micro3!"


@app.route("/test3")
def test():
    return Response('{"result": true, "description": "Microservice3 works"}', status=200, mimetype="json")


def register():
    while True:
        try:
            connection = consul.Consul(host="consul", port=8500)
            connection.agent.service.register(
                "micro3", address="micro3", port=5000)
            break
        except:
            logging.warning("Consul is down, reconnecting...")
            time.sleep(5)


def deregister():
    connection = consul.Consul(host='consul', port=8500)
    connection.agent.service.deregister(
        "micro3", address="micro3", port=5000)


if __name__ == "__main__":
    logging.basicConfig(format="%(message)s", level=1 * 10)
    logging.getLogger("pika").setLevel(logging.WARNING)
    logging.getLogger("sqlite3").setLevel(logging.WARNING)
    register()
    try:
        logging.info("Start.")
        app.run(host="0.0.0.0", threaded=True)
    finally:
        deregister()
