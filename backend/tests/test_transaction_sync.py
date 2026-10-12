import os
import tempfile
import time
import unittest
from pathlib import Path

from app.services.transaction_sync.central_ingest import CentralIngestService, IngestEventItem
from app.services.transaction_sync.store import TransactionEvent, TransactionStore
from app.services.transaction_sync.sync_manager import SyncManager


class TransactionSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_dir = Path(self.tmp.name)
        self.store_db = str(self.db_dir / "store_pos.db")
        self.central_db = str(self.db_dir / "central.db")
        self.store = TransactionStore(self.store_db)
        self.central = CentralIngestService(self.central_db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_enqueue_and_durability_across_restarts(self):
        # 1. Enqueue transactions in store
        ev1 = TransactionEvent("tx-1", "store-001", "T1", 3, time.time())
        ev2 = TransactionEvent("tx-2", "store-001", "T2", 5, time.time())
        self.assertTrue(self.store.enqueue(ev1))
        self.assertTrue(self.store.enqueue(ev2))

        # Check status
        st = self.store.status()
        self.assertEqual(st["pending_count"], 2)
        self.assertEqual(st["synced_count"], 0)

        # 2. Simulate process restart by opening a new TransactionStore instance on the same DB
        store_reopened = TransactionStore(self.store_db)
        st2 = store_reopened.status()
        self.assertEqual(st2["pending_count"], 2)
        pending = store_reopened.get_pending()
        self.assertEqual([e.event_id for e in pending], ["tx-1", "tx-2"])

    def test_idempotent_enqueue_duplicate_rejected(self):
        ev = TransactionEvent("tx-dup", "store-001", "T1", 2, time.time())
        self.assertTrue(self.store.enqueue(ev))
        # Second enqueue with identical ID should return False (ignored)
        self.assertFalse(self.store.enqueue(ev))
        self.assertEqual(self.store.status()["total_count"], 1)

    def test_idempotent_central_ingest(self):
        now = time.time()
        events = [
            IngestEventItem(event_id="e-1", store_id="store-001", terminal_id="T1", item_count=2, created_at=now),
            IngestEventItem(event_id="e-2", store_id="store-001", terminal_id="T1", item_count=1, created_at=now),
        ]
        res1 = self.central.ingest_batch("store-001", events)
        self.assertEqual(res1["accepted"], 2)
        self.assertEqual(res1["duplicates"], 0)

        # Ingest the same batch again -> exactly 0 accepted, 2 duplicates
        res2 = self.central.ingest_batch("store-001", events)
        self.assertEqual(res2["accepted"], 0)
        self.assertEqual(res2["duplicates"], 2)

        # Central stats should report exactly 2 total transactions
        self.assertEqual(self.central.stats()["total_transactions"], 2)

    def test_sync_manager_mark_synced_flow(self):
        ev = TransactionEvent("tx-sync-1", "store-001", "T1", 4, time.time())
        self.store.enqueue(ev)

        # Ingest into central directly to simulate successful roundtrip
        item = IngestEventItem(
            event_id=ev.event_id,
            store_id=ev.store_id,
            terminal_id=ev.terminal_id,
            item_count=ev.item_count,
            created_at=ev.created_at,
        )
        self.central.ingest_batch("store-001", [item])

        # Mark as synced in local store
        synced_count = self.store.mark_synced(["tx-sync-1"])
        self.assertEqual(synced_count, 1)

        st = self.store.status()
        self.assertEqual(st["pending_count"], 0)
        self.assertEqual(st["synced_count"], 1)

    def test_sync_manager_disconnection_simulation(self):
        ev = TransactionEvent("tx-offline-1", "store-001", "T1", 1, time.time())
        self.store.enqueue(ev)

        sm = SyncManager(self.store, "http://invalid-central:9999/central/ingest", "store-001")
        sm.simulate_disconnect()

        res = sm.sync_once()
        self.assertEqual(res["status"], "disconnected")
        self.assertEqual(res["synced"], 0)
        # Event remains pending
        self.assertEqual(self.store.status()["pending_count"], 1)

    def test_store_mark_failed_records_reason(self):
        ev = TransactionEvent("tx-fail-1", "store-001", "T1", 2, time.time())
        self.store.enqueue(ev)

        self.store.mark_failed(["tx-fail-1"], "Central validation rejected")
        st = self.store.status()
        self.assertEqual(st["pending_count"], 0)
        self.assertEqual(st["failed_count"], 1)

    def test_multi_batch_pending_ordering(self):
        t0 = time.time()
        for i in range(10):
            self.store.enqueue(TransactionEvent(f"tx-order-{i}", "store-001", "T1", i + 1, t0 + i))

        batch = self.store.get_pending(limit=5)
        self.assertEqual(len(batch), 5)
        self.assertEqual(batch[0].event_id, "tx-order-0")
        self.assertEqual(batch[4].event_id, "tx-order-4")


if __name__ == "__main__":
    unittest.main()
