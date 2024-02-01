import requests
import uuid
import sqlite3
import time
import json
import pytest

data_folder = "../data"


def test_event():
    event_name = str(uuid.uuid4())
    r1 = requests.get(
        f"http://localhost:8001/addevent?name={event_name}&date=20221004&tickets=5")
    assert r1.status_code == 201, "Test if event has been added"

    time.sleep(1)
    r2 = requests.get(
        f"http://localhost:8001/addevent?name=event&date=20221004&tickets=5")
    assert r2.status_code == 400, "Test if the same event can been added"
    time.sleep(1)
    r3 = requests.get(
        f"http://localhost:8001/deleteevent?id=ad6152c2-3d96-43d1-b2a3-e9d46140b3cf")
    assert r3.status_code == 201, "Test if event has been deleted"
    time.sleep(1)
    r4 = requests.get(
        f"http://localhost:8001/events")
    assert r4.status_code == 200, "Test if the list of events is returned"


def test_ticket():

    r1 = requests.get(
        f"http://localhost:8002/reserveticket?event=87b6239a-6de8-452a-b00b-394abd636d0a&name=MickyMouse")
    assert r1.status_code == 201, "Test if tickets have been reserved"
    r2 = requests.get(
        f"http://localhost:8002/deleteticket?id=2191e77f-73e4-4757-a17e-cc5d931d3b59")
    assert r2.status_code == 201, "Test if ticket has been deleted"
    r3 = requests.get(
        f"http://localhost:8002/tickets")
    assert r3.status_code == 200, "Test if the list of ticksts is returned"

    r4 = requests.get(
        f"http://localhost:8002/searchtickets?date=20221004&tickets=2"
    )
    assert r4.status_code == 200, "Test if events have 2 tickets left"
