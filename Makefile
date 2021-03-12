run: install
	octoprint serve
	@echo "Run Called"

test: install
	rm -f testfiles/*.translate*
	python3 test.py
	@echo "Test Called"

install: .install

.install: setup.py
	octoprint dev plugin:install
	@touch .install
	@echo "Install called"

# .install: octoprint_translatemodel/src/translate.cpp setup.py
# 	octoprint dev plugin:install
# 	@touch .install
# 	@echo "Install called"

clean:
	rm .install
	rm *.so

send:
	git-scp faker "~/.octoprint/plugins/OctoPrint-GcodeLeveling" -y
	ssh faker "source ~/oprint/bin/activate && cd ~/.octoprint/plugins/OctoPrint-GcodeLeveling && octoprint dev plugin:install"
	ssh faker sudo service octoprint restart
	ssh faker tail -f .octoprint/logs/octoprint.log
