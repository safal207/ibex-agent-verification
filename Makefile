.PHONY: install test demo clean

install:
	python -m pip install -e .

test:
	PYTHONPATH=src python -m unittest discover -s tests -v

demo:
	PYTHONPATH=src ./scripts/run_fixture_demo.sh

clean:
	rm -rf artifacts build dist *.egg-info src/*.egg-info
