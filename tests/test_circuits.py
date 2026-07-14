from nexus.circuits import CircuitBreaker, CircuitState


def test_trips_open_and_recovers(tmp_path):
    path = tmp_path / "c.json"
    br = CircuitBreaker(failure_threshold=2, cooldown_s=0.0, path=path)
    assert br.can_execute("local")
    br.record_failure("local", "boom")
    assert br.can_execute("local")  # still closed (1 fail)
    br.record_failure("local", "boom2")
    assert br.get("local").state == CircuitState.OPEN
    # cooldown 0 → half-open allowed
    assert br.can_execute("local")
    assert br.get("local").state == CircuitState.HALF_OPEN
    br.record_success("local")
    assert br.get("local").state == CircuitState.CLOSED
