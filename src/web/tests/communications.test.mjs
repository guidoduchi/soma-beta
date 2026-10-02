import {test} from 'node:test';
import assert from 'node:assert/strict';
import {validChronology} from '../.test-build/data/communications-contracts.js';

test('owner chronology preserves canonical whole seconds and explicit unknown without accepting provider milliseconds',()=>{
  assert.equal(validChronology({known:true,utc_epoch_seconds:1790812800,source_kind:'RECEIVED_TIME'}),true);
  assert.equal(validChronology({known:false,utc_epoch_seconds:null,source_kind:'UNKNOWN'}),true);
  for(const value of [null,{known:false,utc_epoch_seconds:0,source_kind:'UNKNOWN'},
    {known:true,utc_epoch_seconds:1.5,source_kind:'SENT_TIME'}, {known:true,utc_epoch_seconds:null,source_kind:'RECEIVED_TIME'},
    {known:true,utc_epoch_seconds:1790812800,source_kind:'UNKNOWN'},
    {known:true,utc_epoch_ms:1790812800000,source_kind:'RECEIVED_TIME'},
    {known:true,utc_epoch_seconds:1790812800,provider_time_source_epoch_ms:1790812800000,source_kind:'RECEIVED_TIME'}]) {
    assert.equal(validChronology(value),false);
  }
});
