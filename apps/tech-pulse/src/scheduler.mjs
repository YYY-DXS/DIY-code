import { dateInTimezone, timeInTimezone } from "./ranker.mjs";

export class Scheduler {
  constructor({ store, run }) {
    this.store = store;
    this.run = run;
    this.timer = null;
    this.checking = false;
  }

  start() {
    if (this.timer) return;
    this.timer = setInterval(() => this.check(), 20_000);
    this.timer.unref?.();
    setTimeout(() => this.check(), 2_000).unref?.();
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  async check() {
    if (this.checking) return;
    this.checking = true;
    try {
      const config = await this.store.getConfig();
      if (!config.enabled) return;
      const now = new Date();
      if (timeInTimezone(now, config.timezone) !== config.editionTime) return;
      const today = dateInTimezone(now, config.timezone);
      const state = await this.store.getState();
      if (state.lastRunDate === today) return;
      await this.run("scheduled");
    } catch (error) {
      console.error("Scheduler error:", error);
    } finally {
      this.checking = false;
    }
  }
}
