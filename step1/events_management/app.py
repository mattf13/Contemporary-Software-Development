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

from step1.tickets_management.app import search

app = Flask(__name__)

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

    mq_connection = pika.BlockingConnection(pika.ConnectionParameters("rabbitmq"))
    channel = mq_connection.channel()
    channel.exchange_declare(exchange="events", exchange_type="direct")
    
    data_to_send = {"id": str(id), "name": name}
    channel.basic_publish(exchange="events", routing_key="added", body=json.dumps(data_to_send))
    mq_connection.close()

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

    mq_connection = pika.BlockingConnection(pika.ConnectionParameters("rabbitmq"))
    channel = mq_connection.channel()
    channel.exchange_declare(exchange="events", exchange_type="direct")
    
    data_to_send = {"id": id}
    channel.basic_publish(exchange="events", routing_key="deleted", body=json.dumps(data_to_send))
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

def connect_to_mq():
    while True:
        time.sleep(10)

        try:
            return pika.BlockingConnection(pika.ConnectionParameters(host="rabbitmq"))
        except Exception as e:
            logging.warning(f"Could not start listening to the message queue, retrying...")


def listen_to_events(channel):
    channel.start_consuming()

if __name__ == "__main__":
    logging.basicConfig(format="%(message)s", level=1 * 10)
    logging.getLogger("pika").setLevel(logging.WARNING)
    logging.getLogger("sqlite3").setLevel(logging.WARNING)


    mq_connection = connect_to_mq()

    channel = mq_connection.channel()
    channel.exchange_declare(exchange="events", exchange_type="direct")
    channel.exchange_declare(exchange="tickets", exchange_type="direct")
    result = channel.queue_declare(queue="", exclusive=True)
    queue_name = result.method.queue
    channel.queue_bind(exchange="events", queue=queue_name, routing_key="added")
    channel.queue_bind(exchange="events", queue=queue_name, routing_key="deleted")
    channel.queue_bind(exchange="tickets", queue=queue_name, routing_key="added")
    channel.queue_bind(exchange="tickets", queue=queue_name, routing_key="deleted")
    channel.basic_consume(queue=queue_name, on_message_callback=search, auto_ack=True)

    logging.info("Waiting for messages.")

    thread = threading.Thread(target=listen_to_events, args=(channel,), daemon=True)
    thread.start()
    try:
            logging.info("Start.")
            app.run(host="0.0.0.0", threaded=True)
    finally:
            mq_connection.close()
