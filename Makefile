install: .install

test: install testfile-clean
	python3 test.py
	@echo "Test Called"

testfile-clean:
	rm -f testfiles/*-GCL*

clean-test: clean test
.install: octoprint_gcodeleveling/src/parse.cpp octoprint_gcodeleveling/src/fit.cpp octoprint_gcodeleveling/src/vector.cpp setup.py
	python3 setup.py build
	python3 setup.py install
	@touch .install
	@echo "Install called"

clean:
	rm -f .install
	rm -f *.so
	rm -f octoprint_gcodeleveling/*.pyc
	rm -rf octoprint_gcodeleveling/__pycache__
	rm -rf build

send:
	git-scp faker "~/.octoprint/plugins/OctoPrint-GcodeLeveling" -y
	ssh faker "source ~/oprint/bin/activate && cd ~/.octoprint/plugins/OctoPrint-GcodeLeveling && make install"
	ssh faker sudo service octoprint restart
	ssh faker tail -f .octoprint/logs/octoprint.log
