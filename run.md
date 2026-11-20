SANDBOX_PARAMS='{"qd_risk_threshold_pct": 5.6, "horizon_years": 10}' python3 sandbox_bundle.py run nb1


SANDBOX_PARAMS='{"qd_risk_threshold_pct": 5.6, "horizon_years": 10, "ethnicity_source": "ethnicity"}' python3 sandbox_bundle.py run nb1


for s in c1 c2; do for k in 39156-5 8302-2 3141-9; do bash tools/enclave.sh values $s.Observation ObservationValue --where "ObservationCode_Code = '$k'"; done; done


python3 sandbox_bundle.py audit-close 20261119T054135Z_nb00_data_profile_b068d0 --reason "terminal closed before run_end (19 Nov)"



****
python3 sandbox_bundle.py bundle-info

python3 sandbox_bundle.py audit-close 20261119T054135Z_nb00_data_profile_b068d0 --reason "terminal closed before run_end (19 Nov)"

python3 sandbox_bundle.py run all
