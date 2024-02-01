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
    return "Hello from events management!"


@app.route('/addevent')
def addevent():
    id = uuid.uuid4()
    name = request.args.get("name")
    date = request.args.get("date")
    max_no_tickets = request.args.get("tickets")

    db_connection = sqlite3.connect(
        "/home/data/events.db", isolation_level=None)
    cursor = db_connection.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS events (id text, name text, date integer, max_no_tickets integer)")

    cursor.execute("SELECT COUNT(id) FROM events WHERE name = ?", (name,))
    already_exists = cursor.fetchone()[0]
    if already_exists > 0:
        return Response('{"result": false, "error": 2, "description": "Events already exists"}', status=400, mimetype="application/json")

    cursor.execute("INSERT INTO events (id, name, date, max_no_tickets) VALUES (?, ?, ?, ?)", (str(
        id), str(name), int(date), int(max_no_tickets)))
    cursor.close()
    db_connection.close()

    mq_connection = pika.BlockingConnection(
        pika.ConnectionParameters("rabbitmq"))
    channel = mq_connection.channel()
    channel.exchange_declare(exchange="events", exchange_type="direct")

    data_to_send = {"id": str(id), "name": name}
    channel.basic_publish(
        exchange="events", routing_key="added", body=json.dumps(data_to_send))
    mq_connection.close()
    db_connection2 = sqlite3.connect(
        "/home/data/tickets.db", isolation_level=None)
    cursor2 = db_connection2.cursor()
    cursor2.execute(
        "CREATE TABLE IF NOT EXISTS events (id text, name text, date integer, max_no_tickets integer)")

    cursor2.execute("SELECT COUNT(id) FROM events WHERE name = ?", (name,))
    already_exists = cursor2.fetchone()[0]
    if already_exists > 0:
        return Response('{"result": false, "error": 2, "description": "Events already exists"}', status=400, mimetype="application/json")

    cursor2.execute("INSERT INTO events (id, name, date, max_no_tickets) VALUES (?, ?, ?, ?)", (str(
        id), str(name), int(date), int(max_no_tickets)))
    cursor2.close()
    db_connection2.close()

    return Response('{"result": true, "description": "Event has been added."}', status=201, mimetype="application/json")


@app.route("/deleteevent")
def delete():
    id = request.args.get("id")

    if id == None:
        return Response('{"result": false, "error": 1, "description": "Cannot proceed because you did not provide an id for the event."}', status=400, mimetype="application/json")

    db_connection = sqlite3.connect(
        "/home/data/events.db", isolation_level=None)
    cursor = db_connection.cursor()

    cursor.execute("SELECT COUNT(id) FROM events WHERE id = ?", (id,))
    already_exists = cursor.fetchone()[0]
    if already_exists == 0:
        return Response('{"result": true, "description": "The event associated with the following id does not exist"}', status=201, mimetype="application/json")

    cursor.execute("DELETE FROM events WHERE id = ?", (id, ))
    cursor.close()
    db_connection.close()

    mq_connection = pika.BlockingConnection(
        pika.ConnectionParameters("rabbitmq"))
    channel = mq_connection.channel()
    channel.exchange_declare(exchange="events", exchange_type="direct")

    data_to_send = {"id": id}
    channel.basic_publish(
        exchange="events", routing_key="deleted", body=json.dumps(data_to_send))
    mq_connection.close()

    return Response('{"result": true, "description": "The event has been deleted"}', status=201, mimetype="application/json")


@app.route("/events")
def events():
    if os.path.exists("/home/data/events.db"):
        db_connection = sqlite3.connect(
            "/home/data/events.db", isolation_level=None)
        cursor = db_connection.cursor()
        cursor.execute("SELECT * FROM events")
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return Response(json.dumps({"events": rows}), status=200, mimetype="application/json")

    return Response(json.dumps({"events": []}), status=200, mimetype="application/json")


def register():
    while True:
        try:
            connection = consul.Consul(host="consul", port=8500)
            connection.agent.service.register(
                "events_management", address="events_management", port=5000)
            break
        except:
            logging.warning("Consul is down, reconnecting...")
            time.sleep(5)


def deregister():
    connection = consul.Consul(host='consul', port=8500)
    connection.agent.service.deregister(
        "events_management", address="events_management", port=5000)


def connect_to_mq():
    while True:
        time.sleep(10)

        try:
            return pika.BlockingConnection(pika.ConnectionParameters(host="rabbitmq"))
        except Exception as e:
            logging.warning(
                f"Could not start listening to the message queue, retrying...")


def listen_to_events(channel):
    channel.start_consuming()


if __name__ == "__main__":
    logging.basicConfig(format="%(message)s", level=1 * 10)
    logging.getLogger("pika").setLevel(logging.WARNING)
    logging.getLogger("sqlite3").setLevel(logging.WARNING)

    db_connection = sqlite3.connect(
        "/home/data/events.db", isolation_level=None)
    cursor = db_connection.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS events (id text, name text, date integer, max_no_tickets integer)")
    cursor.close()
    db_connection.close()

    register()
    mq_connection = connect_to_mq()

    channel = mq_connection.channel()
    channel.exchange_declare(exchange="events", exchange_type="direct")
    channel.exchange_declare(exchange="tickets", exchange_type="direct")
    result = channel.queue_declare(queue="", exclusive=True)
    queue_name = result.method.queue
    channel.queue_bind(exchange="events", queue=queue_name,
                       routing_key="added")
    channel.queue_bind(exchange="events", queue=queue_name,
                       routing_key="deleted")
    channel.queue_bind(exchange="tickets", queue=queue_name,
                       routing_key="added")
    channel.queue_bind(exchange="tickets", queue=queue_name,
                       routing_key="deleted")
    logging.info("Waiting for messages.")

    thread = threading.Thread(target=listen_to_events,
                              args=(channel,), daemon=True)
    thread.start()
    try:
        logging.info("Start.")
        app.run(host="0.0.0.0", threaded=True)
    finally:
        deregister()
        mq_connection.close()
