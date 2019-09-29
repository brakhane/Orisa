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
        <b-card bg-variant="dark" text-variant="white">
          <div class="card-text">
            <div class="float-right">
              <b-btn @click="reset" class="mr-4">{{ $t("cfg.undo") }}</b-btn>
              <b-btn @click="save" variant="primary">
                <font-awesome-icon icon="spinner" pulse v-if="saving"></font-awesome-icon>
                <span v-else>{{ $t("cfg.save") }}</span>
              </b-btn>
            </div>
            <p
              class="lead"
              v-if="has_validation_errors"
            >{{ $t("cfg.fix-val-errors") }}</p>
            <p
              class="lead"
              v-else-if="save_error"
            >{{ $t("cfg.error-saving") }}</p>
            <p class="lead" v-else>{{ $t("cfg.unsaved") }}</p>
          </div>
        </b-card>
      </div>
    </transition>
    <b-container>
      <h1>{{ $t("cfg.configure-for", { guild_name }) }}</h1>
      <vue-markdown :source="$t('cfg.lead-info', {link: 'https://discord.gg/ZKzBEDF'})" class="lead" :anchorAttributes="{target: '_blank'}"/>
      <b-alert variant="warning" class="my-4" show dismissible v-if="higher_roles.length > 0">
        <h5 class="alert-heading">{{ $t("cfg.not-top-role-head") }}</h5>
        <vue-markdown :source="
          $t('cfg.not-top-role-desc', {
            with_the_following_roles: $t('cfg.with-the-following-roles', {
              count: higher_roles.length
            })
          })
        "/>
        <ul>
          <li v-for="role in higher_roles" :key="role">{{ role }}</li>
        </ul>
        <vue-markdown :anchorAttributes="{target: '_blank', class: 'alert-link'}" :source="
          $t('cfg.drag-orisa-role', { link: 'https://support.discordapp.com/hc/article_attachments/115001756771/Role_Management_101_Update.gif' })
        "/>
      </b-alert>
      <b-alert variant="success" class="my-4" show dismissible v-else>
        <h5 class="alert-heading">{{ $t("cfg.top-role-head") }}</h5>
        <vue-markdown :source="$t('cfg.top-role-desc')"/>
      </b-alert>
      <b-form :novalidate="true">
        <b-card :header="$t('cfg.general-settings-hdr', { guild_name })" class="mb-3">
          <b-form-checkbox
            class="custom-switch"
            v-model="guild_config.show_sr_in_nicks_by_default"
          >{{ $t("cfg.allow-sr-in-nick") }}&nbsp;
            <font-awesome-icon id="always-show-sr-help" icon="question-circle"></font-awesome-icon>
          </b-form-checkbox>&nbsp;
          <b-popover target="always-show-sr-help" triggers="hover click">
            <vue-markdown :source="$t('cfg.allow-sr-in-nick-tt')"/>
          </b-popover>
          <b-form-checkbox
            class="custom-switch"
            v-model="guild_config.post_highscores"
          >{{ $t("cfg.post-hs") }}&nbsp;
            <font-awesome-icon id="post-highscores-help" icon="question-circle"></font-awesome-icon>
          </b-form-checkbox>&nbsp;
          <b-popover target="post-highscores-help" triggers="hover click">
            <vue-markdown :source="$t('cfg.post-hs-tt')"/>
          </b-popover>
          <b-form-group
            label-cols-sm="4" label-cols-lg="3"
            :label="$t('cfg.post-hs-time')"
            :invalid-feedback="validation_errors.post_highscore_time"
            :disabled="!guild_config.post_highscores"
          >
            <b-form-input type="time" v-model="guild_config.post_highscore_time" :state="val_state(validation_errors.post_highscore_time)"/>
          </b-form-group>
          <hr class="hr-3">
          <b-form-group
           label-cols-sm="4" label-cols-lg="3"
           :label="$t('cfg.lang')"
          >
            <template v-if="!lang_fully_translated" #description>
              <vue-markdown class="alert alert-warning" :source="$t('cfg.lang-incomplete-engage',
                {lang: lang_native_name, link: 'https://weblate.orisa.rocks/engage/orisa/'})
              " :anchorAttributes="{target: '_blank'}"/>
            </template>
            <template v-else-if="!lang_config_fully_translated" #description>
              <vue-markdown class="alert alert-info" :source="$t('cfg.lang-config-incomplete-engage',
                {lang: lang_native_name, link: 'https://weblate.orisa.rocks/engage/orisa/'})
              " :anchorAttributes="{target: '_blank'}"/>
            </template>
            <b-form-select v-model="guild_config.locale">
              <optgroup :label="$t('cfg.lang-complete')">
                <template v-for="info in translationInfo.complete">
                  <option :key="info.code" :value="info.code">{{ info.native_name }}
                    <template v-if="info.percent_translated < 100">({{ Math.round(info.percent_translated) }}% translated)</template>
                  </option>
                </template>
              </optgroup>
              <template v-if="translationInfo.incomplete.length">
                <optgroup :label="$t('cfg.lang-incomplete')">
                  <template v-for="info in translationInfo.incomplete">
                    <option :key="info.code" :value="info.code">{{ info.native_name }} ({{ Math.round(info.percent_translated) }}% translated)</option>
                  </template>
                </optgroup>
              </template>
            </b-form-select>
          </b-form-group>
          <b-form-group
            label-cols-sm="4" label-cols-lg="3"
            :label="$t('cfg.reg-msg')"
            :invalid-feedback="validation_errors.extra_register_text"
          >
            <template #description>
              <vue-markdown
                :anchorAttributes="{target: '_blank'}"
                :source="$t('cfg.reg-msg-desc', {
                link: 'https://support.discordapp.com/hc/en-us/articles/210298617-Markdown-Text-101-Chat-Formatting-Bold-Italic-Underline-'
              })"/>
            </template>
            <b-form-textarea
              :state="val_state(validation_errors.extra_register_text)"
              v-model="guild_config.extra_register_text"
              :placeholder="$t('cfg.reg-msg-placeholder')"
              :rows="2"
            ></b-form-textarea>
          </b-form-group>

          <b-form-group
            label-cols-sm="4" label-cols-lg="3"
            :state="val_state(validation_errors.listen_channel_id)"
            :invalid-feedback="validation_errors.listen_channel_id"
            :label="$t('cfg.listen-chan')"
          >
            <template #description>
              <vue-markdown :source="$t('cfg.listen-chan-desc')"/>
            </template>
            <channel-selector
              :state="val_state(validation_errors.listen_channel_id)"
              v-model="guild_config.listen_channel_id"
              :channels="channels"
            ></channel-selector>
          </b-form-group>

          <b-form-group
            label-cols-sm="4" label-cols-lg="3"
            :state="val_state(validation_errors.congrats_channel_id)"
            :invalid-feedback="validation_errors.congrats_channel_id"
            :label="$t('cfg.congrats-chan')"
          >
            <template #description>
              <vue-markdown :source="$t('cfg.congrats-chan-desc')"/>
            </template>
            <channel-selector
              :state="val_state(validation_errors.congrats_channel_id)"
              v-model="guild_config.congrats_channel_id"
              :channels="channels"
            ></channel-selector>
          </b-form-group>
        </b-card>

        <b-card
          bg-variant="info"
          text-variant="white"
          class="mb-3 text-justify"
          v-if="guild_config.managed_voice_categories.length == 0"
          :header="$t('cfg.no-mgt-voice-chan-hdr')"
        >
          <p
            class="lead"
            v-t="'cfg.no-mgt-voice-chan-lead'"
          ></p>
          <vue-markdown :source="$t('cfg.no-mgt-voice-chan-text')"/>
        </b-card>
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
        <b-btn variant="primary" @click="add_cat">
          <font-awesome-icon icon="folder-plus"/>&nbsp;{{ $t('cfg.add-mgt-cat') }}
        </b-btn>
      </b-form>
      <div class="py-5" v-t="'cfg.footer'"></div>
    </b-container>
  </div>
  <div v-else>
    <b-alert
      variant="danger"
      show
      v-if="load_failed"
      v-t="'cfg.load-failed'"
    ></b-alert>
    <div v-else>{{ $t('cfg.loading') }}
      <font-awesome-icon icon="spinner" pulse></font-awesome-icon>
    </div>
  </div>
</template>

<script>

import { library } from '@fortawesome/fontawesome-svg-core'
import {
  faSpinner,
  faFolderPlus,
  faQuestionCircle
} from '@fortawesome/free-solid-svg-icons'
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'
import { isEqual, isEmpty, cloneDeep } from 'lodash'
import i18next from 'i18next'
import translationInfo from '@/generated/translation_info.json'

const ChannelSelector = () => import(/* webpackChunkName: "channel-selector" */'@/components/ChannelSelector')
const ManagedVoiceCategory = () => import(/* webpackChunkName: "managed-voice-category" */'@/components/ManagedVoiceCategory')

library.add(faSpinner, faFolderPlus, faQuestionCircle)

export default {
  name: 'config',
  components: {
    ChannelSelector,
    ManagedVoiceCategory,
    FontAwesomeIcon
  },
  methods: {
    val_errors_mvc (index) {
      if (
        this.validation_errors.managed_voice_categories &&
        this.validation_errors.managed_voice_categories.length > index
      ) {
        return this.validation_errors.managed_voice_categories[index]
      } else {
        return {}
      }
    },

    val_state (obj) {
      if (obj) {
        return false
      } else {
        return this.has_validation_errors ? true : null
      }
    },

    remove_cat (index) {
      this.guild_config.managed_voice_categories.splice(index, 1)
    },

    add_cat () {
      this.guild_config.managed_voice_categories.push({
        category_id: null,
        channel_limit: 5,
        remove_unknown: true,
        prefixes: [],
        show_sr_in_nicks: true
      })
    },

    reset () {
      this.validation_errors = {}
      this.save_error = false
      this.guild_config = cloneDeep(this.orig_guild_config)
    },

    save () {
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
    unsaved_changes () {
      return !isEqual(this.guild_config, this.orig_guild_config)
    },
    has_validation_errors () {
      return !isEmpty(this.validation_errors)
    },
    shake_if_problem () {
      if (this.has_validation_errors || this.save_error) {
        return 'shake'
      } else {
        return ''
      }
    },
    higher_roles () {
      var myPos = this.roles.indexOf(this.my_top_role)
      return this.roles.slice(myPos + 1)
    },

    lang_fully_translated () {
      return this.translationInfo.complete.some((e) => e.code === this.guild_config.locale)
    },

    lang_config_fully_translated () {
      return this.current_lang_info.web_percent_translated >= 90
    },

    current_lang_info () {
      const locale = this.guild_config.locale
      let all = [...this.translationInfo.complete, ...this.translationInfo.incomplete]
      for (let el of all) {
        if (el.code === locale) {
          return el
        }
      }
      throw Error(`${this.guild_config.locale} not found in translationInfo`)
    },

    lang_native_name () {
      return this.current_lang_info.name
    }
  },
  props: ['token'],
  data () {
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
      translationInfo,
      datePickerOptions: {
        format: '%H:%M',
        useCurrent: false
      }
    }
  },
  mounted () {
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
    transform: translateX(-5px);
  }

  20%,
  80%,
  90% {
    transform: translateX(5px);
  }

  30%,
  50% {
    transform: translateX(-10px);
  }

  40%,
  60% {
    transform: translateX(10px);
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
</style>
