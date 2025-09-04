FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
		build-essential \
		cmake \
		gdb \
		git \
		make \
		perftest \
		iproute2 \
		ethtool \
		net-tools \
		curl \
		openssh-client \
		vim \
		gcc \
		libibverbs-dev \
		librdmacm-dev \
		&& rm -rf /var/lib/apt/lists/*

WORKDIR /home
COPY client* /home/
COPY server* /home/
COPY Makefile /home/
COPY message.h /home/
COPY metric_api* /home/
COPY prometheus* /home/

RUN make -C /home -j

CMD ["sleep", "3600"]
