# Docker Image for pydtm

[
  ![](https://img.shields.io/docker/v/foorschtbar/pydtm?style=plastic&sort=date)
  ![](https://img.shields.io/docker/pulls/foorschtbar/pydtm?style=plastic)
  ![](https://img.shields.io/docker/stars/foorschtbar/pydtm?style=plastic)
  ![](https://img.shields.io/docker/image-size/foorschtbar/pydtm?style=plastic)
  ![](https://img.shields.io/github/workflow/status/foorschtbar/pydtm-docker/CI%20Workflow?style=plastic)
](https://hub.docker.com/repository/docker/foorschtbar/pydtm)
[
  ![](https://img.shields.io/github/last-commit/foorschtbar/pydtm-docker?style=plastic)
](https://github.com/foorschtbar/pydtm-docker)

Docker Container for [pydtm](https://github.com/cite/pydtm) (Python (Euro)DOCSIS (3.0) Traffic Meter). This tool uses a DVB-C capable video card (e.g. a cheap USB stick) to measure the EuroDOCSIS 3.0 traffic per frequency, allowing you to venture an educated guess about your local segment's utilization. 

* GitHub: [foorschtbar/pydtm-docker](https://github.com/foorschtbar/pydtm-docker)
* Docker Hub: [foorschtbar/pydtm](https://hub.docker.com/r/foorschtbar/pydtm)

## Usage

Example docker-compose configuration:

```yml
version: "3"

services:
  awtrix:
    image: foorschtbar/pydtm
    restart: unless-stopped
    devices:
      - "/dev/dvb"
    environment:
      - PYDTM_FREQUENCIES=114:256,130:256,138:256,146:256,602:256,618:256,626:256,642:256,650:256,658:256,666:256,674:256,682:256,690:256,698:64,706:64,714:64,722:64,730:64,738:64,746:64,754:64,762:64,770:64,778:64,786:64,794:64,802:64,810:64,818:64,826:64,834:64
      #- PYDTM_ADAPTER=0
      #- PYDTM_CARBON=localhost:2003
      #- PYDTM_DEBUG=True
      #- PYDTM_PREFIX=docsis
      #- PYDTM_STEP=60
      #- PYDTM_TUNER=0
```

## FAQ

### How and why does this even  work?

EuroDOCSIS 3.0 uses standard DVB-C mechanisms to transport it's data: It's encoded as a standard MPEG Transport Stream on [PID](https://en.wikipedia.org/wiki/MPEG_transport_stream#Packet_Identifier_\(PID\)) 8190 with either 64- or 256-[QAM](https://en.wikipedia.org/wiki/QAM_\(television\)) modulation with a symbol rate of 6952ksyms/s. Since cable is a shared medium, determining the total amount of data transferred and comparing this to the total amount possible after [FEC](https://en.wikipedia.org/wiki/Forward_error_correction) (which is about 51Mbit/s for 256-QAM and 34 MBit/s for 64-QAM) will show you how much capacity is used.

### How do I determine downstream frequencies?

Take a look at your cable modem's management pages.

### Wait, I can read my neighbours data with this?

No, you can't.

### This is downstream only, right?

Yes. 

### Recommendation for a DVB-C usb tuner?

Yes, the [Xbox One Digital TV Tuner](https://www.linuxtv.org/wiki/index.php/Xbox_One_Digital_TV_Tuner) works very well and is cheap. For the Xbox One Digital TV Tuner copy the two firmware files from the firmware in this repo folder to the `/lib/firmware` folder on the Docker HOST. Attach the tuner and check kernel log with `dmsg`. 

Working example:

```shell
dvb-usb: found a 'Microsoft Xbox One Digital TV Tuner' in cold state, will try to load a firmware
dvb-usb: downloading firmware from file 'dvb-usb-dib0700-1.20.fw'
dib0700: firmware started successfully.
dvb-usb: found a 'Microsoft Xbox One Digital TV Tuner' in warm state.
dvb-usb: will pass the complete MPEG2 transport stream to the software demuxer.
dvbdev: DVB: registering new adapter (Microsoft Xbox One Digital TV Tuner)
usb 1-1.4: media controller created
dvbdev: dvb_create_media_entity: media entity 'dvb-demux' registered.
mn88472 11-0018: Panasonic MN88472 successfully identified
tda18250 11-0060: NXP TDA18250BHN/M successfully identified
usb 1-1.4: DVB: registering adapter 0 frontend 0 (Panasonic MN88472)...
dvbdev: dvb_create_media_entity: media entity 'Panasonic MN88472' registered.
dvb-usb: Microsoft Xbox One Digital TV Tuner successfully initialized and connected.
[...]
mn88472 11-0018: downloading firmware from file 'dvb-demod-mn88472-02.fw'
```

## Credits

The Container is based on [cite/pydtm](https://github.com/cite/pydtm) from [Stefan Förster](https://www.incertum.net/post/2019/pydtm_1/)