import sqlite3
import uuid
from flask import request
from flask import Flask
from flask import Response
from flask import jsonify
import requests
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
    return "Hello from micro1!"


@app.route("/test")
def test():
    if not request.is_json:
        return Response('{"result": false, "error": 1, "description": "Error."}', status=400, mimetype="json")
    data = request.get_json()
    result = call_micro2(data)
    return result


def call_micro2(data):

    try:
        response = requests.post(
            f"http://localhost:8004/test2", json=data)
        if response.status_code == 200:
            return response.json()
        else:
            time.sleep(0.005)
            return call_micro3(data)
    except Exception as e:
        print(e)
        return call_micro3(data)


def call_micro3(data):
    try:
        response = requests.post(f"http://localhost:8005/test3", json=data)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception("Error while calling micro3")
    except Exception as e:
        print(e)
        return {"error": "Could not call either micro2 or micro3"}


def consulcheck(service_name):
    try:
        response = requests.get(
            f"http://localhost:8500/ui/dc1/services/{service_name}")
        if response.status_code == 200:
            return Response('{"result": true, "description": "Microservice {service_name} works"}', status=201, mimetype="json")
        else:
            raise Exception("Error while checking service in Consul")
    except Exception as e:
        print(e)
        return None


def register():
    while True:
        try:
            connection = consul.Consul(host="consul", port=8500)
            connection.agent.service.register(
                "micro1", address="micro1", port=5000)
            break
        except:
            logging.warning("Consul is down, reconnecting...")
            time.sleep(5)


def deregister():
    connection = consul.Consul(host='consul', port=8500)
    connection.agent.service.deregister(
        "micro1", address="micro1", port=5000)


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
