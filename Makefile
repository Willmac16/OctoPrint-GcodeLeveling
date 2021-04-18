run: install
	octoprint serve
	@echo "Run Called"

test: install
	rm -f testfiles/*-GCL*
	python3.8 test.py
	@echo "Test Called"

install: .install

.install: octoprint_gcodeleveling/src/parse.cpp octoprint_gcodeleveling/src/vector.cpp setup.py
	octoprint dev plugin:install
	@touch .install
	@echo "Install called"

clean:
	rm .install
	rm *.so

send:
	git-scp faker "~/.octoprint/plugins/OctoPrint-GcodeLeveling" -y
	ssh faker "source ~/oprint/bin/activate && cd ~/.octoprint/plugins/OctoPrint-GcodeLeveling && make install"
	ssh faker sudo service octoprint restart
	ssh faker tail -f .octoprint/logs/octoprint.log
