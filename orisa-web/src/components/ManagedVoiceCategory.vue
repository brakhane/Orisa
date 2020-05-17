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
  <div class="section no-bottom-padding">
    <div class="container">
      <div class="card">
        <div class="card-header">
          <div class="card-header-title">
            <div class="container">
              <b-field
                horizontal
                :label="$t('mvc.cat-prepend')"
                :type="val_type(validation_errors.category_id)"
                :message="validation_errors.category_id"
              >
                <b-select v-model="category.category_id" expanded>
                  <template v-for="chan in channels">
                    <option
                      :key="chan.id"
                      :value="chan.id"
                      v-if="chan.type == 4"
                      >{{ chan.name }}</option
                    >
                  </template>
                </b-select>
              </b-field>
            </div>
          </div>
          <div class="card-header-icon">
            <b-button
              type="is-danger is-outlined"
              @click="$emit('delete-cat-clicked')"
            >
              <b-icon icon="trash-can" />
            </b-button>
          </div>
        </div>
        <div class="card-content">
          <div class="card">
            <div class="card-header">
              <div class="card-header-title" v-t="'mvc.settings-hdr'"></div>
            </div>
            <div class="card-content">
              <b-switch v-model="category.show_sr_in_nicks"
                >{{ $t("mvc.show-sr") }}&nbsp;</b-switch
              >
              <b-dropdown>
                <b-icon icon="help-circle" slot="trigger"></b-icon>
                <b-dropdown-item custom>
                  <div class="container">
                    <p>{{ $t("mvc.show-sr-tt") }}</p>
                  </div>
                </b-dropdown-item>
              </b-dropdown>
              <br />
              <b-switch v-model="category.remove_unknown">
                <vue-markdown
                  class="is-inline-block"
                  :source="$t('mvc.remove-unknown-sr')"
                />&nbsp;
              </b-switch>
              <b-dropdown>
                <b-icon icon="help-circle" slot="trigger"></b-icon>
                <b-dropdown-item custom>
                  <div class="container">
                    <vue-markdown :source="$t('mvc.remove-unknown-sr-tt')" />
                  </div>
                </b-dropdown-item>
              </b-dropdown>
              <hr class="hr-4" />
              <b-field
                horizontal
                :label="$t('mvc.mngt-pos')"
                :message="$t('mvc.mngt-pos-tt')"
              >
                <b-field horizontal>
                  <b-radio-button
                    v-model="category.managed_position"
                    native-value="top"
                    >{{ $t("mvc.mngt-pos-top") }}
                  </b-radio-button>
                  <b-radio-button
                    v-model="category.managed_position"
                    native-value="bottom"
                    >{{ $t("mvc.mngt-pos-bottom") }}</b-radio-button
                  >
                </b-field>
              </b-field>
              <b-field
                horizontal
                :type="val_type(validation_errors.channel_limit)"
                :message="validation_errors.channel_limit"
                :label="$t('mvc.chan-limit')"
              >
                <b-numberinput
                  v-model.number="category.channel_limit"
                  min="1"
                  max="99"
                ></b-numberinput>
              </b-field>
            </div>
          </div>
          <hr class="hr" />
          <div class="card">
            <div class="card-header">
              <div class="card-header-title" v-t="'mvc.mngt-prefixes'"></div>
            </div>
            <div class="card-content">
              <b-message
                type="is-warning"
                v-if="category.prefixes.length == 0"
                >{{ $t("mvc.no-prefixes") }}</b-message
              >
              <div
                :key="index"
                v-for="(prefix, index) in category.prefixes"
                class="section no-top-padding"
              >
                <div class="card">
                  <div class="card-content">
                    <div class="columns">
                      <div class="column is-three-quarters">
                        <b-field
                          :type="val_type(val_errors_prefixes(index).name)"
                          :label="$t('mvc.chan-name')"
                          :message="
                            val_errors_prefixes(index).name ||
                              $t('mvc.chan-name-desc')
                          "
                        >
                          <b-input
                            v-model="prefix.name"
                            :placeholder="$t('mvc.prefix-placeholder')"
                          ></b-input>
                        </b-field>
                      </div>
                      <div class="column">
                        <b-field
                          :type="val_type(val_errors_prefixes(index).limit)"
                          :label="$t('mvc.user-limit')"
                          :message="
                            val_errors_prefixes(index).limit ||
                              $t('mvc.user-limit-desc')
                          "
                        >
                          <b-numberinput
                            v-model.number="prefix.limit"
                            min="0"
                            max="99"
                          ></b-numberinput>
                        </b-field>
                      </div>
                    </div>

                    <b-button
                      type="is-danger is-outlined"
                      @click="delete_prefix(category, index)"
                    >
                      <b-icon icon="trash-can" />
                    </b-button>
                  </div>
                </div>
              </div>
              <b-button type="is-primary" @click="add_prefix(category)">
                <b-icon icon="plus" size="is-small"></b-icon>
                &nbsp;{{ $t("mvc.add-prefix") }}
              </b-button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { isEmpty } from 'lodash-es'

export default {
  name: 'managed-voice-category',
  data () {
    return {}
  },
  computed: {
    has_validation_errors () {
      return !isEmpty(this.validation_errors)
    }
  },
  methods: {
    val_errors_prefixes (index) {
      if (
        this.validation_errors.prefixes &&
        this.validation_errors.prefixes.length > index
      ) {
        return this.validation_errors.prefixes[index]
      } else {
        return {}
      }
    },
    val_type (obj) {
      if (obj) {
        return 'is-danger'
      } else {
        return this.has_validation_errors ? 'is-success' : ''
      }
    },

    delete_prefix (category, index) {
      category.prefixes.splice(index, 1)
    },

    add_prefix (category) {
      category.prefixes.push({
        name: null,
        limit: 0
      })
    }
  },
  props: ['category', 'validation_errors', 'channels', 'index']
}
</script>
