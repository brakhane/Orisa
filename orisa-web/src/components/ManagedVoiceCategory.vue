<template>
  <div class="card mb-3 bg-light">
    <div class="card-header">
      <b-input-group prepend="Category">
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
        >Show SR of members in managed channels&nbsp;
          <font-awesome-icon :id="`show-sr-help-${index}`" icon="question-circle"></font-awesome-icon>
        </b-form-checkbox>
        <b-popover :target="`show-sr-help-${index}`" triggers="hover click">
          <p>
            When this setting is on, Orisa will adjust the channel name so that the lowest and highest SR of its members are shown (e.g. "Comp #1 [1234-2345]"). She will also update the nicknames
            of every member in that channel to show their SR (or rank, if that member has configured it via
            <code>!ow format</code>). Unfortunately, these updated nicknames will only show in the
            channel list after a reload of Discord due to a Discord bug (that Discord isn't going to fix).
          </p>
          <p>It is recommended to turn this setting on for Overwatch channel categories</p>
        </b-popover>
        <br>
        <b-form-checkbox class="custom-switch" v-model="category.remove_unknown">
          Remove unknown channels with
          <code>#</code> in this category
          &nbsp;
          <font-awesome-icon :id="`remove-unknown-help-${index}`" icon="question-circle"></font-awesome-icon>
          <b-popover :target="`remove-unknown-help-${index}`" triggers="hover click">
            <p>
              With this setting active, Orisa will automatically remove any empty channels in this category that contain a
              <code>#</code>, as they are probably left over channels. For example, if you
              rename "Comp" to "Competitive", there now will be at least aComp #1 channel that should get removed.
            </p>
            <p>When this settings is off, Orisa will only touch channels that she knows are hers (begin with the prefix and then followed by a
              <code>#</code>)
            </p>
            <p>Unless you have manually created channels in this category that contain a
              <code>#</code>, it is recommended to leave this setting on
            </p>
          </b-popover>
        </b-form-checkbox>
        <hr class="hr-4">
        <b-form-group
          horizontal
          :state="val_state(validation_errors.channel_limit)"
          :invalid-feedback="validation_errors.channel_limit"
          :label-cols="4"
          label="Maximum number of channels per prefix"
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
      <b-card header="Managed prefixes" no-body>
        <b-card-body>
          <b-alert
            variant="warning"
            :show="category.prefixes.length == 0"
          >There are no prefixes configured yet!</b-alert>
          <div
            class="row bg-light m-2 p-2"
            :key="index"
            v-for="(prefix, index) in category.prefixes"
          >
            <b-form-group
              class="col-6 col-md-7 col-lg-8"
              :state="val_state(val_errors_prefixes(index).name)"
              :invalid-feedback="val_errors_prefixes(index).name"
              label="Prefix"
              description="The text before the number (and SR if &quot;Show SR&quot; is active)"
            >
              <b-form-input
                :state="val_state(val_errors_prefixes(index).name)"
                v-model="prefix.name"
                placeholder="e.g. Comp, or Quick Play"
              ></b-form-input>
            </b-form-group>
            <b-form-group
              class="col-6 col-md-5 col-lg-4"
              :state="val_state(val_errors_prefixes(index).limit)"
              :invalid-feedback="val_errors_prefixes(index).limit"
              label="User limit"
              description="The maximum number of people allowed in the created voice channels. 0 means no limit."
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
            <font-awesome-icon icon="plus"/>Add a managed channel prefix
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
