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
              <b-btn @click="reset" class="mr-4">Reset</b-btn>
              <b-btn @click="save" variant="primary">
                <font-awesome-icon icon="spinner" pulse v-if="saving"></font-awesome-icon>
                <span v-else>Save</span>
              </b-btn>
            </div>
            <p
              class="lead"
              v-if="has_validation_errors"
            >Please fix the validation errors before saving.</p>
            <p
              class="lead"
              v-else-if="save_error"
            >There was a problem saving, please try again later</p>
            <p class="lead" v-else>You have unsaved changes!</p>
          </div>
        </b-card>
      </div>
    </transition>
    <b-container>
      <h1>Configure Orisa for {{ guild_name }}</h1>
      <p
        class="lead"
      >The save button will appear when you have unsaved changes. After you have saved your changes, you can close this window.</p>
      <p>If you have questions or suggestions, <a target="_blank" href="https://discord.gg/tsNxvFh">join the official Orisa Discord</a>.</p>
      <b-alert variant="warning" class="my-4" show dismissible v-if="higher_roles.length > 0">
        <h5 class="alert-heading">The Orisa role is not the top role!</h5>
        <p>
          Discord disallows nickname changes when the member whose nickname should be changed has a higher role than Orisa.
          You need to move the Orisa role all the way to the top if you want her to be able to change all nicknames. Currently, Orisa won't be able to
          update the nicknames of members with the following
          <span
            v-if="higher_roles.length ==1"
          >role:</span>
          <span v-else>roles:</span>
        </p>
        <ul>
          <li v-for="role in higher_roles" :key="role">{{ role }}</li>
        </ul>
        <p>
          You can simply drag and drop the Orisa role in the
          <em>Server Settings &gt; Roles</em> screen,
          <a
            href="https://support.discordapp.com/hc/article_attachments/115001756771/Role_Management_101_Update.gif"
            target="_blank"
            class="alert-link"
          >like this</a>.
          Orisa will not get more permissions by this, it simply allows her to change more nicknames (the nickname of the server owner cannot be changed by her whatever you do).
        </p>
        <p>
          <em>Do not give the Orisa role Administrator rights!</em> It won't help, and is a potential security risk if Orisa has an exploitable bug.
        </p>
      </b-alert>
      <b-alert variant="success" class="my-4" show dismissible v-else>
        <h5 class="alert-heading">The Orisa role is the top role</h5>
        <p>Orisa will be able to change the nicknames of all your members, with the exception of the server owner.</p>
      </b-alert>
      <b-form :novalidate="true">
        <b-card :header="`General Settings for ${guild_name}`" class="mb-3">
          <b-form-checkbox
            class="custom-switch"
            v-model="guild_config.show_sr_in_nicks_by_default"
          >Always show SR (or rank) in nicknames by default&nbsp;
            <font-awesome-icon id="always-show-sr-help" icon="question-circle"></font-awesome-icon>
          </b-form-checkbox>
          <b-popover target="always-show-sr-help" triggers="hover click">
            <p>
              When this setting is on, Orisa will always update the nicknames of all registered users to show their SR in the name (
              <code>Orisa</code> becomes
              <code>Orisa [2345]</code>).
            </p>
            <p>If you feel your server members focus too much on the SR ("I don't listen to a silver player"), you can turn this setting off.</p>
            <p>
              When turned off, your server members can still force their SR to be displayed by issuing the
              <code>!ow alwaysshowsr</code> command.
            </p>
            <p>If unsure, activate this setting, and only turn it off if people react negatively to it.</p>
          </b-popover>
          <hr class="hr-3">
          <b-form-group
            horizontal
            label="Register message"
            :invalid-feedback="validation_errors.extra_register_text"
            description="Optional server specific text that should be shown in the welcome message after a member registered with <code>!ow register</code>. This message is <em>not</em> shown when a user joins this server. Can use <a target=&quot;_blank&quot; href=&quot;https://support.discordapp.com/hc/en-us/articles/210298617-Markdown-Text-101-Chat-Formatting-Bold-Italic-Underline-&quot;>Discord Markdown</a>."
          >
            <b-form-textarea
              :state="val_state(validation_errors.extra_register_text)"
              v-model="guild_config.extra_register_text"
              placeholder="e.g.
Don't forget to use `!ow setroles` to set your roles; also don't play Genji."
              :rows="2"
            ></b-form-textarea>
          </b-form-group>

          <b-form-group
            horizontal
            :state="val_state(validation_errors.listen_channel_id)"
            :invalid-feedback="validation_errors.listen_channel_id"
            label="Listen Channel"
            description="In which channel should Orisa listen for commands? This channel will also be used to post the daily SR highscore table. Orisa always reacts to commands via DM. Also, the <code>!ow help</code> command works in any channel."
          >
            <channel-selector
              :state="val_state(validation_errors.listen_channel_id)"
              v-model="guild_config.listen_channel_id"
              :channels="channels"
            ></channel-selector>
          </b-form-group>

          <b-form-group
            horizontal
            :state="val_state(validation_errors.congrats_channel_id)"
            :invalid-feedback="validation_errors.congrats_channel_id"
            label="Congrats Channel"
            description="When a member reaches a new highest rank (e.g. Silver → Gold), Orisa will publically congratulate him/her in this channel. It is highly recommended to select the channel where members chat about OW (Orisa will <strong>only</strong> post 'rank up' messages), but it can also be the same as &quot;Listen Channel&quot;."
          >
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
          header="No managed voice channels"
        >
          <p
            class="lead"
          >Orisa can help you dynamically create and delete voice channels on demand (not just for OW) and optionally show the SR in the channel names.</p>
          <p>
            Instead of manually creating
            <em>Comp #1</em> to
            <em>Comp #5</em>
            channels which are empty most of the time, you can have a single
            <em>Comp #1</em> channel, and as soon as a person joins,
            Orisa will automatically create an empty
            <em>Comp #2</em> channel, and optionally show the SR range in the channel name (e.g.
            <em>Comp #1 [1234-1804]</em>).
          </p>
          <p>
            If
            <em>Comp #1</em> becomes empty again,
            <em>Comp #2</em> will automatically be removed; if on the other hand
            <em>Comp #3</em> is used, but
            <em>Comp #1</em> and
            <em>Comp #2</em> are empty,
            <em>Comp #2</em> will be removed, and
            <em>Comp #3</em> will be renamed to
            <em>Comp #2</em>.
          </p>
          <p>This way, there will always be one (and only one) empty voice channel.</p>
          <p>There are currently no managed voice channels. Click the button below to configure them.</p>
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
          <font-awesome-icon icon="folder-plus"/>Add a managed channel category
        </b-btn>
      </b-form>
      <div class="py-5">Thank you for using Orisa!</div>
    </b-container>
  </div>
  <div v-else>
    <b-alert
      variant="danger"
      show
      v-if="load_failed"
    >Something went wrong while loading the data. This link might have expired. Try requesting a new one. If that doesn't help, try again later...</b-alert>
    <div v-else>Loading
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
      my_top_role: null
    }
  },
  mounted () {
    this.$http.get(`config_data/${this.token}`).then(
      response => {
        this.channels = response.data.channels
        this.guild_config = response.data.guild_config
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
