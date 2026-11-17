# Requirement 3 targets. On Windows without make use the python commands shown (same thing).
PY ?= python

phase1:        ## py scripts/run_phase1.py
	$(PY) scripts/run_phase1.py
phase2:        ## py scripts/run_phase2.py
	$(PY) scripts/run_phase2.py
bench-final:   ## full interleaved V0..V4 profile + report
	$(PY) scripts/bench_final.py
demo:          ## full before/after demo (about 8 min)
	$(PY) scripts/demo_req3.py
demo-quick:    ## short demo (about 3 min)
	$(PY) scripts/demo_req3.py --quick
demo-saved:    ## print the saved results without running anything live
	$(PY) scripts/demo_req3.py --from-results

req4-test:     ## Requirement 4 integration tests (stack must be running)
	docker compose --profile test --profile req4 run --rm --no-deps tester tests -m "req4 or req4_latency" -v -s
req4-demo:     ## Requirement 4 evidence/preflight demo
	$(PY) scripts/demo_req4.py
req4-demo-quick:
	$(PY) scripts/demo_req4.py --quick

.PHONY: phase1 phase2 bench-final demo demo-quick demo-saved req4-test req4-demo req4-demo-quick
