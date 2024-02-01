import sqlite3
import uuid
from flask import request
from flask import Flask
from flask import Response
import logging
import pika
import json
import consul
import time
import os
from datetime import datetime
import threading
import requests


app = Flask(__name__)


@app.route("/")
def hello():
    return "Hello from tickets management!"


@app.route("/reserveticket")
def reserve():
    event_id = request.args.get("event")
    name = request.args.get("name")
    no_of_sold_tickets = 0
    id = uuid.uuid4()

    db_connection = sqlite3.connect(
        "/home/data/tickets.db", isolation_level=None)
    cursor = db_connection.cursor()

    cursor.execute(
        "CREATE TABLE IF NOT EXISTS tickets (id text, event_id text, buyer_name text, date integer, no_of_sold_tickets integer)")

    cursor.execute(
        "SELECT max_no_tickets FROM events WHERE id = ?", (event_id,))
    max_no_tickets = cursor.fetchone()[0]
    no_of_sold_tickets += 0

    cursor.execute(
        "SELECT date FROM events WHERE id = ?", (event_id,))
    date = cursor.fetchone()[0]

    cursor.execute("INSERT INTO tickets (id, event_id, buyer_name, date, no_of_sold_tickets) VALUES (?, ?, ?, ?, ?)", (str(
        id), str(event_id), str(name), int(date), no_of_sold_tickets+1))

    cursor.execute(
        "SELECT COUNT(no_of_sold_tickets) FROM tickets WHERE event_id = ?", (event_id,))
    no_of_sold_tickets = int(cursor.fetchone()[0])
    if no_of_sold_tickets == max_no_tickets:
        return Response('{"result": false, "error": 2, "description": "Event is sold out"}', status=400, mimetype="application/json")

    db_connection.close()

    mq_connection = pika.BlockingConnection(
        pika.ConnectionParameters("rabbitmq"))
    channel = mq_connection.channel()
    channel.exchange_declare(exchange="ticket", exchange_type="direct")

    data_to_send = {"id": str(id), "name": name}
    channel.basic_publish(exchange="tickets",
                          routing_key="added", body=json.dumps(data_to_send))
    mq_connection.close()

    return Response(json.dumps({"ticket ": str(id)}), status=201, mimetype="application/json")


@app.route("/deleteticket")
def deleteticket():
    id = request.args.get("id")

    if id == None:
        return Response('{"result": false, "error": 1, "description": "Cannot proceed because you did not provide an id for the ticket."}', status=400, mimetype="application/json")

    db_connection = sqlite3.connect(
        "/home/data/tickets.db", isolation_level=None)
    cursor = db_connection.cursor()

    cursor.execute("SELECT COUNT(id) FROM tickets WHERE id = ?", (id,))
    already_exists = cursor.fetchone()[0]
    if already_exists == 0:
        return Response('{"result": true, "description": "The ticket associated with the following id does not exist"}', status=201, mimetype="application/json")

    cursor.execute("DELETE FROM tickets WHERE id = ?", (id, ))
    cursor.close()
    db_connection.close()

    mq_connection = pika.BlockingConnection(
        pika.ConnectionParameters("rabbitmq"))
    channel = mq_connection.channel()
    channel.exchange_declare(exchange="tickets", exchange_type="direct")

    data_to_send = {"id": id}
    channel.basic_publish(exchange="tickets",
                          routing_key="deleted", body=json.dumps(data_to_send))
    mq_connection.close()

    return Response('{"result": true, "description": "The ticket has been deleted"}', status=201, mimetype="application/json")


@app.route("/tickets")
def tickets():
    if os.path.exists("/home/data/events.db"):
        db_connection = sqlite3.connect(
            "/home/data/tickets.db", isolation_level=None)
        cursor = db_connection.cursor()
        cursor.execute("SELECT id, event_id, date FROM tickets")
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return Response(json.dumps({"tickets": rows}), status=200, mimetype="application/json")

    return Response(json.dumps({"tickets": []}), status=200, mimetype="application/json")


@app.route("/searchtickets")
def search():
    date = request.args.get("date")
    tickets = request.args.get("tickets")

    db_connection = sqlite3.connect(
        "/home/data/tickets.db", isolation_level=None)
    cursor = db_connection.cursor()
    cursor.execute(
        "SELECT COUNT(no_of_sold_tickets) FROM tickets WHERE date = ?", (date, ))
    count_tickets_left = cursor.fetchone()[0]
    cursor.execute(
        "SELECT max_no_tickets FROM events WHERE date = ?", (date, ))
    max_no_tickets = cursor.fetchone()[0]
    if (max_no_tickets-count_tickets_left >= int(tickets)):
        cursor.execute("SELECT * FROM events WHERE date = ?", (date, ))
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return Response(json.dumps({"events": rows}), status=200, mimetype="application/json")
    cursor.close()
    db_connection.close()
    return Response(json.dumps({"events": []}), status=200, mimetype="application/json")


def register():
    while True:
        try:
            connection = consul.Consul(host="consul", port=8500)
            connection.agent.service.register(
                "tickets_management", address="tickets_management", port=5000)
            break
        except:
            logging.warning("Consul is down, reconnecting...")
            time.sleep(5)


def deregister():
    connection = consul.Consul(host='consul', port=8500)
    connection.agent.service.deregister(
        "tickets_management", address="tickets_management", port=5000)


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


def subscribe(exchange_name, routing_key, callback_function):
    mq_connection = connect_to_mq()
    channel = mq_connection.channel()
    channel.exchange_declare(exchange=exchange_name, exchange_type="direct")
    result = channel.queue_declare(queue="", exclusive=True)
    queue_name = result.method.queue
    channel.queue_bind(exchange=exchange_name,
                       queue=queue_name, routing_key=routing_key)
    channel.basic_consume(
        queue=queue_name, on_message_callback=callback_function, auto_ack=True)
    return channel


def subscribe_all(routing_keys, callback_functions):
    channels = []
    for i in range(len(routing_keys)):
        routing_key = routing_keys[i]
        callback_function = callback_functions[i]
        channel = subscribe(routing_key, callback_function)
        channels.append(channel)
    return channels


def find_service(name):
    connection = consul.Consul(host="consul", port=8500)
    _, services = connection.health.service(name, passing=True)
    for service_info in services:
        address = service_info["Service"]["Address"]
        port = service_info["Service"]["Port"]
        return address, port

    return None, None


if __name__ == "__main__":
    logging.basicConfig(format="%(message)s", level=1 * 10)
    logging.getLogger("pika").setLevel(logging.WARNING)
    logging.getLogger("sqlite3").setLevel(logging.WARNING)

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
    channel.basic_consume(
        queue=queue_name, on_message_callback=search, auto_ack=True)

    logging.info("Waiting for messages.")
    if os.path.exists("/home/data/tickets.db"):
        database_is_initialized = True
    else:
        db_connection = sqlite3.connect(
            "/home/data/tickets.db", isolation_level=None)
        cursor = db_connection.cursor()
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS tickets (id text, event_id text, buyer_name text, date integer, no_of_sold_tickets integer)")
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS events (id text, name text, date integer, max_no_tickets integer)")

        while True:
            try:
                address, port = find_service("events")
                data = requests.get(
                    f"http://{address}:{port}/events").json()
                for entry in data["events"]:
                    cursor.execute(
                        "INSERT INTO events VALUES (?, ?, ?)", (entry["id"], entry["name"], entry["max_no_tickets"]))
                break
            except:
                time.sleep(5)
            cursor.close()
            db_connection.close()
            database_is_initialized = True
    if not database_is_initialized:
        logging.error("Cannot initialize database.")
    else:
        try:
            logging.info("Start.")
            app.run(host="0.0.0.0", threaded=True)
        finally:
            deregister()
