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
  <div class="card mb-3 bg-light">
    <div class="card-header">
      <b-input-group :prepend="$t('mvc.cat-prepend')">
        <b-form-select
          :state="val_state(validation_errors.category_id)"
          v-model="category.category_id"
        >
          <template v-for="chan in channels">
            <option :key="chan.id" :value="chan.id" v-if="chan.type == 4">{{ chan.name }}</option>
          </template>
        </b-form-select>
        <b-input-group-append>
          <b-btn variant="outline-danger" @click="$emit('delete-cat-clicked')">
            <font-awesome-icon :icon="['far', 'trash-alt']"></font-awesome-icon>
          </b-btn>
        </b-input-group-append>
        <div
          class="invalid-feedback"
          v-if="validation_errors.category_id"
        >{{ validation_errors.category_id }}</div>
      </b-input-group>
    </div>
    <div class="card-body">
      <b-card header="Settings">
        <b-form-checkbox
          class="custom-switch"
          v-model="category.show_sr_in_nicks"
        >{{ $t("mvc.show-sr") }}&nbsp;
        <font-awesome-icon :id="`show-sr-help-${index}`" icon="question-circle"></font-awesome-icon>
        </b-form-checkbox>
        <b-popover :target="`show-sr-help-${index}`" triggers="hover click">
          {{ $t("mvc.show-sr-tt") }}
        </b-popover>
        <br>
        <b-form-checkbox class="custom-switch" v-model="category.remove_unknown">
          <vue-markdown class="d-inline-block" :source="$t('mvc.remove-unknown-sr')"/>
          <font-awesome-icon :id="`remove-unknown-help-${index}`" icon="question-circle"></font-awesome-icon>
          <b-popover :target="`remove-unknown-help-${index}`" triggers="hover click">
            <vue-markdown :source="$t('mvc.remove-unknown-sr-tt')"/>
          </b-popover>
        </b-form-checkbox>
        <hr class="hr-4">
        <b-form-group
          horizontal
          :state="val_state(validation_errors.channel_limit)"
          :invalid-feedback="validation_errors.channel_limit"
          :label-cols="4"
          :label="$t('mvc.chan-limit')"
        >
          <b-form-input
            :state="val_state(validation_errors.channel_limit)"
            class="col-4 col-md-3"
            v-model.number="category.channel_limit"
            type="number"
            min="2"
            max="99"
          ></b-form-input>
        </b-form-group>
      </b-card>
      <hr class="hr-4">
      <b-card :header="$t('mvc.mngt-prefixes')" no-body>
        <b-card-body>
          <b-alert
            variant="warning"
            :show="category.prefixes.length == 0"
          >{{ $t('mvc.no-prefixes') }}</b-alert>
          <div
            class="row bg-light m-2 p-2"
            :key="index"
            v-for="(prefix, index) in category.prefixes"
          >
            <b-form-group
              class="col-6 col-md-7 col-lg-8"
              :state="val_state(val_errors_prefixes(index).name)"
              :invalid-feedback="val_errors_prefixes(index).name"
              :label="$t('mvc.chan-name')"
              :description="$t('mvc.chan-name-desc')"
            >
              <b-form-input
                :state="val_state(val_errors_prefixes(index).name)"
                v-model="prefix.name"
                :placeholder="$t('mvc.prefix-placeholder')"
              ></b-form-input>
            </b-form-group>
            <b-form-group
              class="col-6 col-md-5 col-lg-4"
              :state="val_state(val_errors_prefixes(index).limit)"
              :invalid-feedback="val_errors_prefixes(index).limit"
              :label="$t('mvc.user-limit')"
              :description="$t('mvc.user-limit-desc')"
            >
              <b-form-input
                :state="val_state(val_errors_prefixes(index).limit)"
                v-model.number="prefix.limit"
                type="number"
                min="0"
                max="99"
              ></b-form-input>
            </b-form-group>
            <b-btn variant="outline-danger" @click="delete_prefix(category, index)">
              <font-awesome-icon :icon="['far', 'trash-alt']"></font-awesome-icon>
            </b-btn>
          </div>
        </b-card-body>
        <b-card-body>
          <b-btn variant="primary" @click="add_prefix(category)">
            <font-awesome-icon icon="plus"/>&nbsp;{{ $t("mvc.add-prefix") }}
          </b-btn>
        </b-card-body>
      </b-card>
    </div>
  </div>
</template>
<script>
import { library } from '@fortawesome/fontawesome-svg-core'
import { faTrashAlt } from '@fortawesome/free-regular-svg-icons'
import { faQuestionCircle, faPlus } from '@fortawesome/free-solid-svg-icons'
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'
import { isEmpty } from 'lodash'

library.add(faTrashAlt, faPlus, faQuestionCircle)

export default {
  name: 'managed-voice-category',
  components: {
    FontAwesomeIcon
  },
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
    val_state (obj) {
      if (obj) {
        return false
      } else {
        return this.has_validation_errors ? true : null
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
