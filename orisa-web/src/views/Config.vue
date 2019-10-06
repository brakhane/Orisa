<!--
Orisa, a simple Discord bot with good intentions
Copyright (C) 2018, 2019 Dennis Brakhane

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, version 3 only

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
-->
<template>
  <div v-if="loaded">
    <transition name="fade-drop">
      <div :class="'container fixed-top translucent ' + shake_if_problem" v-if="unsaved_changes">
        <div class="card">
          <div class="card-content">
            <div class="level">
              <div class="level-left">
                <p v-if="has_validation_errors">{{ $t("cfg.fix-val-errors") }}</p>
                <p v-else-if="save_error">{{ $t("cfg.error-saving") }}</p>
                <p v-else>{{ $t("cfg.unsaved") }}</p>
              </div>
              <div class="level-right">
                <div class="buttons">
                  <b-button @click="reset" v-t="'cfg.undo'"></b-button>
                  <b-button @click="save" type="is-primary" :loading="saving" v-t="'cfg.save'"></b-button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </transition>
    <div class="hero is-light">
      <div class="hero-body">
        <div class="container">
          <h1 class="title">{{ $t("cfg.configure-for", { guild_name }) }}</h1>
          <vue-markdown
            :source="$t('cfg.lead-info', {link: 'https://discord.gg/ZKzBEDF'})"
            :anchorAttributes="{target: '_blank'}"
          />
        </div>
      </div>
    </div>

    <div class="section no-bottom-padding">
      <div class="container">
        <b-message
          type="is-warning"
          :title="$t('cfg.not-top-role-head')"
          v-if="higher_roles.length > 0"
        >
          <vue-markdown
            :source="
            $t('cfg.not-top-role-desc', {
              with_the_following_roles: $t('cfg.with-the-following-roles', {
                count: higher_roles.length
              })
            })
          "
          />
          <ul>
            <li v-for="role in higher_roles" :key="role">{{ role }}</li>
          </ul>
          <vue-markdown
            :anchorAttributes="{target: '_blank', class: 'alert-link'}"
            :source="
            $t('cfg.drag-orisa-role', { link: 'https://support.discordapp.com/hc/article_attachments/115001756771/Role_Management_101_Update.gif' })
          "
          />
        </b-message>
        <b-message type="is-success" :title="$t('cfg.top-role-head')" v-else>
          <vue-markdown :source="$t('cfg.top-role-desc')" />
        </b-message>
      </div>
    </div>

    <div class="section no-bottom-padding">
      <div class="container">
        <div class="card">
          <div class="card-header">
            <div class="card-header-title">{{ $t('cfg.general-settings-hdr', { guild_name }) }}</div>
          </div>
          <div class="card-content">
            <b-field>
              <b-switch
                v-model="guild_config.show_sr_in_nicks_by_default"
              >{{ $t("cfg.allow-sr-in-nick") }}&nbsp;</b-switch>
              <b-dropdown>
                <b-icon icon="help-circle" slot="trigger"></b-icon>
                <b-dropdown-item custom>
                  <div class="container">
                    <vue-markdown :source="$t('cfg.allow-sr-in-nick-tt')" />
                  </div>
                </b-dropdown-item>
              </b-dropdown>
            </b-field>
            <b-field>
              <b-switch v-model="guild_config.post_highscores">{{ $t("cfg.post-hs") }}&nbsp;</b-switch>&nbsp;
              <b-dropdown>
                <b-icon icon="help-circle" slot="trigger"></b-icon>
                <b-dropdown-item custom>
                  <div class="container">
                    <vue-markdown :source="$t('cfg.post-hs-tt')" />
                  </div>
                </b-dropdown-item>
              </b-dropdown>
            </b-field>

            <b-field
              :label="$t('cfg.post-hs-time')"
              :type="val_type(validation_errors.post_highscore_time)"
              :message="validation_errors.post_highscore_time"
              horizontal
            >
              <b-clockpicker hour-format="24" v-model="post_highscore_time_jsdate" />
            </b-field>

            <hr class="hr" />

            <b-field :label="$t('cfg.lang')" horizontal>
              <template v-if="!lang_fully_translated" #message>
                <vue-markdown
                  class="alert alert-warning"
                  :source="$t('cfg.lang-incomplete-engage',
                  {lang: lang_native_name, link: 'https://weblate.orisa.rocks/engage/orisa/'})
                "
                  :anchorAttributes="{target: '_blank'}"
                />
              </template>
              <template v-else-if="!lang_config_fully_translated" #message>
                <vue-markdown
                  class="alert alert-info"
                  :source="$t('cfg.lang-config-incomplete-engage',
                  {lang: lang_native_name, link: 'https://weblate.orisa.rocks/engage/orisa/'})
                "
                  :anchorAttributes="{target: '_blank'}"
                />
              </template>
              <b-select v-model="guild_config.locale" expanded>
                <optgroup :label="$t('cfg.lang-complete')">
                  <template v-for="info in translationInfo.complete">
                    <option :key="info.code" :value="info.code">
                      {{ info.native_name }}
                      <template
                        v-if="info.percent_translated < 100"
                      >({{ Math.round(info.percent_translated) }}% translated)</template>
                    </option>
                  </template>
                </optgroup>
                <template v-if="translationInfo.incomplete.length">
                  <optgroup :label="$t('cfg.lang-incomplete')">
                    <template v-for="info in translationInfo.incomplete">
                      <option
                        :key="info.code"
                        :value="info.code"
                      >{{ info.native_name }} ({{ Math.round(info.percent_translated) }}% translated)</option>
                    </template>
                  </optgroup>
                </template>
              </b-select>
            </b-field>

            <div class="field is-horizontal">
              <div class="field-label is-normal">
                <label class="label" v-t="'cfg.reg-msg'"></label>
              </div>
              <div class="field-body">
                <div class="field">
                  <b-input
                    type="textarea"
                    v-model="guild_config.extra_register_text"
                    :placeholder="$t('cfg.reg-msg-placeholder')"
                    rows="2"
                  />
                  <div class="help">
                    <vue-markdown
                      :anchorAttributes="{target: '_blank'}"
                      :source="$t('cfg.reg-msg-desc', {
                      link: 'https://support.discordapp.com/hc/en-us/articles/210298617-Markdown-Text-101-Chat-Formatting-Bold-Italic-Underline-'
                    })"
                    />
                  </div>
                </div>
              </div>
            </div>
            <!--                :label="$t('cfg.reg-msg')"
              :message="validation_errors.extra_register_text"
              :type="val_type(validation_errors.extra_register_text)"
              horizontal
            >
            </b-field>
            -->
            <b-field
              :type="val_type(validation_errors.listen_channel_id)"
              :message="validation_errors.listen_channel_id"
              :label="$t('cfg.listen-chan')"
              horizontal
              customClass="is-normal"
            >
              <channel-selector
                :type="val_type(validation_errors.listen_channel_id)"
                v-model="guild_config.listen_channel_id"
                :channels="channels"
              ></channel-selector>
              <template #message>
                <vue-markdown :source="$t('cfg.listen-chan-desc')" />
              </template>
            </b-field>

            <b-field
              :type="val_type(validation_errors.congrats_channel_id)"
              :message="validation_errors.congrats_channel_id"
              :label="$t('cfg.congrats-chan')"
              horizontal
              customClass="is-normal"
            >
              <template #description>
                <vue-markdown :source="$t('cfg.congrats-chan-desc')" />
              </template>
              <channel-selector
                :type="val_type(validation_errors.congrats_channel_id)"
                v-model="guild_config.congrats_channel_id"
                :channels="channels"
              ></channel-selector>
            </b-field>
          </div>
        </div>
      </div>
    </div>

    <div class="section no-bottom-padding" v-if="guild_config.managed_voice_categories.length == 0">
      <div class="container">
        <b-message :title="$t('cfg.no-mgt-voice-chan-lead')" type="is-info" :closable="false">
          <vue-markdown :source="$t('cfg.no-mgt-voice-chan-text')" />
        </b-message>
      </div>
    </div>

    <managed-voice-category
      v-else
      v-for="(cat, index) in guild_config.managed_voice_categories"
      :category="cat"
      :channels="channels"
      :validation_errors="val_errors_mvc(index)"
      :key="index"
      :index="index"
      @delete-cat-clicked="remove_cat(index)"
    ></managed-voice-category>

    <div class="section">
      <div class="container">
        <b-button type="is-primary" @click="add_cat">
          <b-icon icon="folder-plus" size="is-small"></b-icon>
          &nbsp;{{ $t('cfg.add-mgt-cat') }}
        </b-button>
      </div>
    </div>

    <footer class="footer">
      <div class="content has-text-centered">
        <p v-t="'cfg.footer'" />
      </div>
    </footer>
  </div>

  <div class="container" v-else>
    <div class="hero is-danger" v-if="load_failed">
      <div class="hero-body">
        <h2 class="subtitle">{{ $t("cfg.load-failed") }}</h2>
      </div>
    </div>
    <b-loading active v-else></b-loading>
  </div>
</template>

<script>

import { isEqual, isEmpty, cloneDeep } from 'lodash'
import i18next from 'i18next'
import translationInfo from '@/generated/translation_info.json'

const ChannelSelector = () => import(/* webpackChunkName: "channel-selector" */'@/components/ChannelSelector')
const ManagedVoiceCategory = () => import(/* webpackChunkName: "managed-voice-category" */'@/components/ManagedVoiceCategory')

export default {
  name: 'config',
  components: {
    ChannelSelector,
    ManagedVoiceCategory
  },
  methods: {
    val_errors_mvc(index) {
      if (
        this.validation_errors.managed_voice_categories &&
        this.validation_errors.managed_voice_categories.length > index
      ) {
        return this.validation_errors.managed_voice_categories[index]
      } else {
        return {}
      }
    },

    val_type(obj) {
      if (obj) {
        return 'is-danger'
      } else {
        return this.has_validation_errors ? 'is-success' : ''
      }
    },

    remove_cat(index) {
      this.guild_config.managed_voice_categories.splice(index, 1)
    },

    add_cat() {
      this.guild_config.managed_voice_categories.push({
        category_id: null,
        channel_limit: 5,
        remove_unknown: true,
        prefixes: [],
        show_sr_in_nicks: true
      })
    },

    reset() {
      this.validation_errors = {}
      this.save_error = false
      this.guild_config = cloneDeep(this.orig_guild_config)
    },

    parse_time(timestr) {
      return new Date(`2000-01-01T${timestr}:00T`)
    },

    save() {
      if (this.saving) return
      this.saving = true
      this.validation_errors = {}
      this.save_error = false
      this.$http
        .put(`guild_config/${this.guild_id}`, this.guild_config, {
          headers: { Authorization: `Bearer ${this.token}` }
        })
        .then(response => {
          this.saving = false
          this.orig_guild_config = cloneDeep(this.guild_config)
          this.validation_errors = {}
        })
        .catch(error => {
          this.saving = false
          if (error.request.status === 400) {
            this.validation_errors = error.response.data
          } else {
            this.save_error = true
            console.error(error)
          }
        })
    }
  },

  watch: {
    'guild_config.locale': function (newVal, oldVal) {
      i18next.changeLanguage(newVal)
    }
  },

  computed: {
    unsaved_changes() {
      return !isEqual(this.guild_config, this.orig_guild_config)
    },
    has_validation_errors() {
      return !isEmpty(this.validation_errors)
    },
    shake_if_problem() {
      if (this.has_validation_errors || this.save_error) {
        return 'shake'
      } else {
        return ''
      }
    },
    higher_roles() {
      var myPos = this.roles.indexOf(this.my_top_role)
      return this.roles.slice(myPos + 1)
    },

    lang_fully_translated() {
      return this.translationInfo.complete.some((e) => e.code === this.guild_config.locale)
    },

    lang_config_fully_translated() {
      return this.current_lang_info.web_percent_translated >= 90
    },

    current_lang_info() {
      const locale = this.guild_config.locale
      let all = [...this.translationInfo.complete, ...this.translationInfo.incomplete]
      for (let el of all) {
        if (el.code === locale) {
          return el
        }
      }
      throw Error(`${this.guild_config.locale} not found in translationInfo`)
    },

    lang_native_name() {
      return this.current_lang_info.name
    },

    post_highscore_time_jsdate: {
      get() {
        return new Date(`2000-01-01T${this.guild_config.post_highscore_time}:00`)
      },

      set(time) {
        const h = `0${time.getHours()}`.slice(-2)
        const m = `0${time.getMinutes()}`.slice(-2)
        this.guild_config.post_highscore_time = `${h}:${m}`
      }
    }

  },
  props: ['token'],
  data() {
    return {
      saving: false,
      orig_guild_config: null,
      channels: null,
      guild_config: null,
      guild_id: null,
      guild_name: null,
      loaded: false,
      load_failed: false,
      validation_errors: {},
      save_error: false,
      roles: null,
      my_top_role: null,
      translationInfo
    }
  },
  mounted() {
    this.$http.get(`config_data/${this.token}`).then(
      response => {
        this.channels = response.data.channels
        this.guild_config = response.data.guild_config
        if (this.guild_config.locale === null) {
          this.guild_config.locale = 'en'
        }
        this.guild_name = response.data.guild_name
        this.guild_id = response.data.guild_id
        this.roles = response.data.roles
        this.my_top_role = response.data.top_role
        this.orig_guild_config = cloneDeep(this.guild_config)
        this.loaded = true
      },
      response => {
        this.load_failed = true
        console.error(response)
      }
    )
  }
}
</script>

<style>
.bounce-enter-active {
  animation: bounce-in 0.5s;
}
.bounce-leave-active {
  animation: bounce-in 0.5s reverse;
}
@keyframes bounce-in {
  0% {
    transform: scale(0);
  }
  50% {
    transform: scale(1.25);
  }
  100% {
    transform: scale(1);
  }
}

.shake {
  animation: shake-it 0.5s;
}

@keyframes shake-it {
  0%,
  100% {
    transform: translateX(0);
  }

  10%,
  70% {
    transform: translateX(-7px);
  }

  20%,
  80%,
  90% {
    transform: translateX(7px);
  }

  30%,
  50% {
    transform: translateX(-14px);
  }

  40%,
  60% {
    transform: translateX(14px);
  }
}

.fade-drop-enter-active,
.fade-drop-leave-active {
  transition: all 0.5s;
}

.fade-drop-enter,
.fade-drop-leave-to {
  transform: translateY(-100px);
  opacity: 0;
}

.translucent {
  opacity: 0.97;
}

.no-bottom-padding {
  padding-bottom: 0;
}

.no-top-padding {
  padding-top: 0;
}

.fixed-top {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 1000;
}
</style>
