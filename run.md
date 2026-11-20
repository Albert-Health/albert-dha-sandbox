SANDBOX_PARAMS='{"qd_risk_threshold_pct": 5.6, "horizon_years": 10}' python3 sandbox_bundle.py run nb1


SANDBOX_PARAMS='{"qd_risk_threshold_pct": 5.6, "horizon_years": 10, "ethnicity_source": "ethnicity"}' python3 sandbox_bundle.py run nb1


for s in c1 c2; do for k in 39156-5 8302-2 3141-9; do bash tools/enclave.sh values $s.Observation ObservationValue --where "ObservationCode_Code = '$k'"; done; done
