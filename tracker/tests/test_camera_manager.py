from eyetracker.camera import CameraManager


class FakeWorker:
    instances = []

    def __init__(self, cam_id, store, world, model_factory):
        self.cam_id = cam_id
        self.started = self.stopped = False
        FakeWorker.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def status(self):
        return {"id": self.cam_id, "enabled": True, "connected": True}


def manager(store, active=True):
    FakeWorker.instances = []
    return CameraManager(store, None, None, worker_cls=FakeWorker, active=active)


def test_starts_one_worker_per_enabled_camera(store):
    m = manager(store)
    m.sync()
    assert sorted(m.workers) == ["left_to_right", "right_to_left"]
    assert all(w.started for w in m.workers.values())


def test_zero_cameras(store):
    for cam in list(store.get()["cameras"]):
        store.remove_item("cameras", cam["id"], save=False)
    m = manager(store)
    m.sync()
    assert m.workers == {} and m.statuses() == []


def test_disable_and_remove_stop_workers(store):
    m = manager(store)
    m.sync()
    left = m.workers["left_to_right"]
    cam = store.camera("left_to_right")
    cam["enabled"] = False
    store.replace_item("cameras", cam, save=False)
    m.sync()
    assert left.stopped and "left_to_right" not in m.workers
    assert m.statuses()[0] == {"id": "left_to_right", "connected": False, "enabled": False, "read_fps": 0,
                               "detect_fps": 0, "size": (0, 0), "people": 0, "error": ""}
    right = m.workers["right_to_left"]
    store.remove_item("cameras", "right_to_left", save=False)
    m.sync()
    assert right.stopped and m.workers == {}


def test_stream_change_restarts_but_pose_change_does_not(store):
    m = manager(store)
    m.sync()
    old = m.workers["left_to_right"]
    cam = store.camera("left_to_right")
    cam["heading"] = 10
    store.replace_item("cameras", cam, save=False)
    m.sync()
    assert m.workers["left_to_right"] is old and not old.stopped
    cam["channel"] = 102
    store.replace_item("cameras", cam, save=False)
    m.sync()
    assert old.stopped and m.workers["left_to_right"] is not old


def test_inactive_manager_starts_nothing(store):
    m = manager(store, active=False)
    m.sync()
    assert m.workers == {} and len(m.statuses()) == 2
