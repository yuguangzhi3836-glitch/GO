from go_hotel.services.outbox import OutboxWorker

if __name__ == "__main__":
    OutboxWorker().run_forever()
