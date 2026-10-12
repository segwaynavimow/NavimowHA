# Changelog

## [1.1.1](https://github.com/segwaynavimow/NavimowHA/compare/NavimowHA-v1.1.0...NavimowHA-v1.1.1) (2026-10-10)


### Bug Fixes

* **navimow:** prevent stale MQTT cache from replacing newer state ([5530aca](https://github.com/segwaynavimow/NavimowHA/commit/5530aca33b3ad224afa6294ca7994d8124021f41))
* **navimow:** recover faster from silent MQTT outages and stale state ([6ddacc3](https://github.com/segwaynavimow/NavimowHA/commit/6ddacc324b8b6228f9d02d092722e8ffbd72e168))
* **navimow:** treat MQTT user info circuit-breaker as non-fatal ([964ea60](https://github.com/segwaynavimow/NavimowHA/commit/964ea6011fa50c15464ad1f21eacdfcc608ce758)), closes [#49](https://github.com/segwaynavimow/NavimowHA/issues/49)

## [1.1.0](https://github.com/segwaynavimow/NavimowHA/compare/NavimowHA-v1.0.0...NavimowHA-v1.1.0) (2026-04-10)


### Features

* add danish translation ([2de5eab](https://github.com/segwaynavimow/NavimowHA/commit/2de5eab0679b68bafc66cb61eff33f3de37c568d))
* Add french translation ([303d3c8](https://github.com/segwaynavimow/NavimowHA/commit/303d3c8187c48636ac23aec293dfcbd9300fc744))


### Bug Fixes

* **navimow:** Fix OAuth token expiration issue after MQTT disconnection ([26c8ed5](https://github.com/segwaynavimow/NavimowHA/commit/26c8ed5bd7853afdb00c61ad27e2344ca8794e3e))
* **navimow:** Fixed MQTT credential refresh and unload logic ([7381489](https://github.com/segwaynavimow/NavimowHA/commit/738148937b92e659ee9c000a1308db5e389ebf22))
* **navimow:** improve MQTT reconnection handling and entity availability ([c04ae31](https://github.com/segwaynavimow/NavimowHA/commit/c04ae312f0685705215b8cfc31c1400d6c96a5e0))
* **navimow:** Optimize re-authentication error handling, distinguishing between deterministic and transient failures ([cb2bd56](https://github.com/segwaynavimow/NavimowHA/commit/cb2bd56eea8be91a8cded3e76dd74c5a5a68301e))
* **navimow:** Optimizes MQTT connection keepalive and reconnection mechanisms ([0f38417](https://github.com/segwaynavimow/NavimowHA/commit/0f384173283644e1a93798993e4152eaeb7f40b3))

## Changelog

所有版本变更将由自动化发布流程生成。
