# camera-in-a-box: see README.md
IMAGE ?= camera-in-a-box:dev
NAME  ?= cam-01

-include .build/SOURCES.env

.PHONY: stage build run shell status logs stop clean

stage:            ## copy camera-server sources into .build/
	./stage.sh

build: stage      ## build the image
	docker buildx build --load -t $(IMAGE) \
	  --build-context sstcam=.build/sstcam-server \
	  --build-context cambridge=.build/cambridge \
	  --build-arg SSTCAM_SERVER_REV=$(SSTCAM_SERVER_REV) \
	  --build-arg SSTCAM_SERVER_BRANCH=$(SSTCAM_SERVER_BRANCH) \
	  --build-arg CAMBRIDGE_REV=$(CAMBRIDGE_REV) .

run:              ## start one camera server (systemd as PID 1)
	docker run -d --name $(NAME) --hostname $(NAME) \
	  --privileged --cgroupns=host -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
	  --tmpfs /run --tmpfs /run/lock --tmpfs /tmp \
	  $(IMAGE)

shell:
	docker exec -it $(NAME) ucam bash

status:
	docker exec $(NAME) ucam systemctl --user list-units 'sstcam*' --all --no-pager

logs:
	docker exec $(NAME) journalctl -f -n 50 --no-pager

stop:
	docker rm -f $(NAME)

clean: stop
	rm -rf .build
